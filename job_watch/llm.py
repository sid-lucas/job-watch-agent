"""Shared LLM access. Public web data: the models of config.MODEL_CHAIN in order, cloud models first,
a local model as last resort. Personal data (the profile): only through local_structured_llm and
local_text_llm, whose chain (config.MATCH_CHAIN) is checked to hold local models only."""
import logging
import os
import re
import threading
import time
from collections import Counter
from functools import cache
from typing import Literal

from dotenv import load_dotenv
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.exceptions import ModelAuthenticationError, ModelPermissionDeniedError, ModelRateLimitError
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_mistralai import ChatMistralAI
from langchain_ollama import ChatOllama

from job_watch import config

load_dotenv()

GEMINI_TIMEOUT = 30     # seconds per request; an overloaded cloud model is replaced by the next one in the chain
MISTRAL_TIMEOUT = 60    # seconds per request
OLLAMA_TIMEOUT = 180    # seconds per request; the local model is the last one, and slow on a long page


class _UnsupportedSchemaKey(logging.Filter):
    """Drop the 'Key ... is not supported in schema, ignoring' warning of langchain_google_genai.

    Gemini ignores keys such as additionalProperties (extra="forbid"): the code validates every
    answer again, so the warning carries no information. Other warnings of that logger stay.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return "is not supported in schema" not in record.getMessage()


logging.getLogger("langchain_google_genai._function_utils").addFilter(_UnsupportedSchemaKey())


_calls: Counter[str] = Counter()     # "provider:model" -> answers; "... failed", "... waited", "... skipped"
_calls_lock = threading.Lock()


class _CallCounter(BaseCallbackHandler):
    """Counts the calls answered (and failed) by one model of the chain."""

    def __init__(self, name: str):
        self.name = name

    def on_llm_end(self, response, **kwargs) -> None:
        with _calls_lock:
            _calls[self.name] += 1

    def on_llm_error(self, error, **kwargs) -> None:
        with _calls_lock:
            _calls[f"{self.name} failed"] += 1


# ---------- rate limits and quotas ----------

RATE_LIMIT_RETRIES = 2          # new attempts on the same model after a per-minute limit
RATE_LIMIT_MAX_WAIT = 60        # seconds; a longer retry delay is not waited for (next model instead)
RATE_LIMIT_DEFAULT_WAIT = 20    # seconds, when the error gives no retry delay

# Models skipped for the rest of the process: daily (or monthly) quota spent, key refused,
# or a 429 that could not be read and came back after one retry
_unavailable: dict[str, str] = {}
_sleep = time.sleep             # replaced in tests

FailureKind = Literal["per_minute", "daily", "unknown_quota", "auth", "other"]


class ModelSkipped(Exception):
    """Raised instead of calling a model already unavailable; the fallback takes the call."""


def _error_chain(error: BaseException):
    """The error and its causes (provider errors are wrapped by the LangChain clients)."""
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        yield error
        error = error.__cause__ or error.__context__


def _quota_ids(error: BaseException) -> list[str]:
    """quotaId values of a Google 429 (structured details first, then the error text)."""
    ids = []
    for item in _error_chain(error):
        details = getattr(item, "details", None)
        if isinstance(details, dict):
            for detail in details.get("error", {}).get("details", []):
                ids += [v.get("quotaId", "") for v in detail.get("violations", []) if isinstance(v, dict)]
    return ids or re.findall(r"""['"]quotaId['"]\s*:\s*['"]([^'"]+)""", str(error))


def _retry_delay(error: BaseException) -> float | None:
    """Seconds to wait as given by the error: Google RetryInfo.retryDelay, or an HTTP Retry-After header."""
    for item in _error_chain(error):
        details = getattr(item, "details", None)
        if isinstance(details, dict):
            for detail in details.get("error", {}).get("details", []):
                if delay := re.fullmatch(r"(\d+(?:\.\d+)?)s", str(detail.get("retryDelay", ""))):
                    return float(delay.group(1))
        response = getattr(item, "response", None)
        header = getattr(getattr(response, "headers", None), "get", lambda name: None)("retry-after")
        if header and re.fullmatch(r"\d+(?:\.\d+)?", header.strip()):
            return float(header)
    if found := re.search(r"""['"]retryDelay['"]\s*:\s*['"](\d+(?:\.\d+)?)s""", str(error)):
        return float(found.group(1))
    return None


def classify_failure(error: BaseException) -> tuple[FailureKind, float | None]:
    """What a failed call means for the model, and the delay to wait when it says so.

    per_minute: wait, then the same model again. daily: quota spent for the day (or month), skip
    the model for the run. auth: key refused (401, 403) or payment required (402: no free tier
    active), skip. unknown_quota: a 429 that cannot be read. other: timeout, overload, bad
    answer... the next model takes this call only.
    """
    if any(isinstance(e, (ModelAuthenticationError, ModelPermissionDeniedError)) for e in _error_chain(error)):
        return "auth", None
    text = " ".join(str(e) for e in _error_chain(error))
    if (any(402 in (getattr(e, "code", None), getattr(e, "status_code", None)) for e in _error_chain(error))
            or re.search(r"\b402\b|payment required", text, re.IGNORECASE)):
        return "auth", None
    rate_limited = (any(isinstance(e, ModelRateLimitError) for e in _error_chain(error))
                    or any(getattr(e, "code", None) == 429 for e in _error_chain(error))
                    or "RESOURCE_EXHAUSTED" in text or re.search(r"\b429\b", text) is not None)
    if not rate_limited:
        return "other", None
    ids = " ".join(_quota_ids(error))
    lowered = text.lower()
    if re.search(r"PerDay|PerMonth", ids) or re.search(r"per day|daily|per month|monthly", lowered):
        return "daily", None
    if re.search(r"PerMinute|PerSecond", ids) or re.search(r"per minute|per second|rate limit", lowered):
        return "per_minute", _retry_delay(error)
    return "unknown_quota", _retry_delay(error)


def _guarded(name: str, runnable: Runnable) -> Runnable:
    """One model of the chain, with the rate-limit policy of classify_failure()."""

    def call(value, config):
        attempts = 0
        while True:
            with _calls_lock:
                if name in _unavailable:
                    _calls[f"{name} skipped"] += 1
                    raise ModelSkipped(f"{name} unavailable for this run ({_unavailable[name]})")
            try:
                return runnable.invoke(value, config)
            except Exception as error:
                kind, delay = classify_failure(error)
                if kind in ("daily", "auth") or (kind == "unknown_quota" and attempts >= 1):
                    with _calls_lock:
                        _unavailable[name] = kind
                    raise
                retries = RATE_LIMIT_RETRIES if kind == "per_minute" else 1
                wait = RATE_LIMIT_DEFAULT_WAIT if delay is None else delay
                if kind == "other" or attempts >= retries or wait > RATE_LIMIT_MAX_WAIT:
                    raise
                attempts += 1
                with _calls_lock:
                    _calls[f"{name} waited"] += 1
                _sleep(wait)

    return RunnableLambda(call, name=f"guarded[{name}]")


def _chain(runnables: list) -> Runnable:
    """Models in order, each with the rate-limit policy, with fallbacks to the next ones."""
    guarded = [_guarded(name, runnable) for name, runnable in runnables]
    return guarded[0].with_fallbacks(guarded[1:]) if len(guarded) > 1 else guarded[0]


def model_calls() -> dict[str, int]:
    """Calls answered and failed per model since the start of the process (a copy)."""
    with _calls_lock:
        return dict(_calls)


def calls_since(before: dict[str, int]) -> dict[str, int]:
    """Calls per model made since an earlier model_calls() snapshot."""
    now = model_calls()
    return {name: count - before.get(name, 0) for name, count in sorted(now.items())
            if count - before.get(name, 0)}


def _client(provider: str, model: str, think: bool | None = None):
    """think: reasoning of a local model (None: config.OLLAMA_THINK)."""
    counter = [_CallCounter(f"{provider}:{model}")]
    if provider == "gemini":
        return ChatGoogleGenerativeAI(model=model, google_api_key=os.environ["GEMINI_API_KEY"],
                                      timeout=GEMINI_TIMEOUT, max_retries=1, callbacks=counter)
    if provider == "mistral":
        return ChatMistralAI(model=model, mistral_api_key=os.environ["MISTRAL_API_KEY"], timeout=MISTRAL_TIMEOUT,
                             max_retries=1, temperature=0, callbacks=counter)
    if provider == "ollama":
        # Reasoning off by default (config.OLLAMA_THINK): slower, and not always compatible with structured output
        think = config.OLLAMA_THINK if think is None else think
        return ChatOllama(model=model, num_ctx=config.OLLAMA_NUM_CTX, temperature=0, reasoning=think,
                          client_kwargs={"timeout": OLLAMA_TIMEOUT}, callbacks=counter)
    raise ValueError(f"Unknown LLM provider: {provider}")


# Optional providers: left out of the chain when their API key is not set (only its presence is checked)
OPTIONAL_KEYS = {"mistral": "MISTRAL_API_KEY"}


def llm_chain() -> list[tuple[str, str]]:
    """Enabled models of config.MODEL_CHAIN, or only one provider when LLM_ONLY is set (e.g. LLM_ONLY=ollama).

    An optional provider without its API key in the environment is left out.
    """
    only = os.environ.get("LLM_ONLY")
    chain = [(p, m) for p, m, enabled in config.MODEL_CHAIN if enabled and (not only or p == only)
             and (p not in OPTIONAL_KEYS or os.environ.get(OPTIONAL_KEYS[p]))]
    if not chain:
        raise ValueError(f"No model left in MODEL_CHAIN for LLM_ONLY={only}")
    return chain


def only_local_left() -> bool:
    """True when every cloud model of the chain is skipped for the rest of the run (daily quota
    spent, key refused): only local models can still answer."""
    with _calls_lock:
        return all(f"{p}:{m}" in _unavailable for p, m in llm_chain() if p not in config.LOCAL_PROVIDERS)


@cache
def structured_llm(schema, models: tuple[tuple[str, str], ...] | None = None):
    """Models of the chain (or the given models), each returning the Pydantic schema, tried in
    order with the rate-limit policy."""
    return _chain([(f"{provider}:{model}", _client(provider, model).with_structured_output(schema))
                   for provider, model in (models or llm_chain())])


@cache
def tool_llm(tools: tuple, models: tuple[tuple[str, str], ...] | None = None):
    """Models of the chain (or the given models), each bound to the given tools, tried in order.

    Binding is done per model before the fallbacks are chained: a fallback model receives
    the same tool schemas. The answer is an AIMessage; its tool_calls are requests only.
    """
    return _chain([(f"{provider}:{model}", _client(provider, model).bind_tools(list(tools)))
                   for provider, model in (models or llm_chain())])


# ---------- local models only (personal data) ----------

class CloudModelRefused(SystemExit):
    """A chain meant for personal data names a cloud model: the program stops."""


def local_models(chain: list[tuple[str, str, bool]]) -> tuple[tuple[str, str], ...]:
    """Enabled models of a chain for personal data. Any cloud model in it, enabled or not, stops the
    program: personal data never goes to a cloud model, not even by a fallback or a later toggle."""
    cloud = [f"{p}:{m}" for p, m, _ in chain if p not in config.LOCAL_PROVIDERS]
    if cloud:
        raise CloudModelRefused(f"MATCH_CHAIN may only hold local models ({', '.join(sorted(config.LOCAL_PROVIDERS))}),"
                                f" found: {', '.join(cloud)}. Personal data never goes to a cloud model.")
    models = tuple((p, m) for p, m, enabled in chain if enabled)
    if not models:
        raise CloudModelRefused("MATCH_CHAIN has no enabled local model")
    return models


@cache
def _local_chain(schema, think: bool, models: tuple[tuple[str, str], ...]):
    return _chain([(f"{p}:{m}", _client(p, m, think).with_structured_output(schema) if schema
                    else _client(p, m, think)) for p, m in models])


def local_structured_llm(schema, think: bool):
    """Local models of config.MATCH_CHAIN returning the Pydantic schema (checked on every call)."""
    return _local_chain(schema, think, local_models(config.MATCH_CHAIN))


def local_text_llm(think: bool):
    """Local models of config.MATCH_CHAIN answering free text (an AIMessage; checked on every call)."""
    return _local_chain(None, think, local_models(config.MATCH_CHAIN))


def call_with_retry(func, *args, attempts: int = 2, wait_seconds: int = 5):
    """Call an LLM function, with one short retry. Return None if every model keeps failing:
    the caller then retries later instead of waiting."""
    for attempt in range(1, attempts + 1):
        try:
            return func(*args)
        except Exception as error:   # any provider error; the type is printed so bugs stay visible
            print(f"          LLM error (all models), attempt {attempt}/{attempts}: "
                  f"{type(error).__name__}: {str(error)[:80]}")
            if attempt < attempts:
                time.sleep(wait_seconds)
    return None