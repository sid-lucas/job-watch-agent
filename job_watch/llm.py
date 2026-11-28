"""Shared LLM access. Public web data: the models of config.MODEL_CHAIN in order, cloud models first,
a local model as last resort. Personal data (the profile, the matching): only through local_call
on config.MATCH_CHAIN, checked to hold local models only."""
from contextlib import contextmanager
from contextvars import ContextVar
import logging
import os
import re
import threading
import time
from collections import Counter
from collections.abc import Callable
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

FailureKind = Literal["per_minute", "daily", "unknown_quota", "auth", "overloaded", "other"]

# A model overloaded (503, 504) this many times in a run is skipped for the rest of it
OVERLOADED_SKIP_AFTER = 2
_overloaded: Counter[str] = Counter()

# Optional line per attempt of a model of a chain ("trying ...", "done in 3s", "failed (504) after
# 90s, next model"), set by the caller around one call (attempts_logged)
_attempt_log: ContextVar[Callable[[str], None] | None] = ContextVar("attempt_log", default=None)


@contextmanager
def attempts_logged(log: Callable[[str], None] | None):
    """Within this block, each attempt of a model of a chain is reported to log."""
    token = _attempt_log.set(log)
    try:
        yield
    finally:
        _attempt_log.reset(token)


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
    active), skip. unknown_quota: a 429 that cannot be read. overloaded: 503 or 504 (model busy,
    deadline expired): the next model takes this call, and the model is skipped for the run after
    OVERLOADED_SKIP_AFTER of them. other: client timeout, bad answer... the next model takes this
    call only.
    """
    if any(isinstance(e, (ModelAuthenticationError, ModelPermissionDeniedError)) for e in _error_chain(error)):
        return "auth", None
    text = " ".join(str(e) for e in _error_chain(error))
    if (any(402 in (getattr(e, "code", None), getattr(e, "status_code", None)) for e in _error_chain(error))
            or re.search(r"\b402\b|payment required", text, re.IGNORECASE)):
        return "auth", None
    if (any({503, 504} & {getattr(e, "code", None), getattr(e, "status_code", None)} for e in _error_chain(error))
            or re.search(r"\b50[34]\b|UNAVAILABLE|DEADLINE_EXCEEDED", text)):
        return "overloaded", None
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


def _error_label(error: BaseException) -> str:
    """Short name of a failure for the attempt lines: the HTTP code when there is one, else the type."""
    for item in _error_chain(error):
        for name in ("code", "status_code"):
            code = getattr(item, name, None)
            if isinstance(code, int) and 400 <= code < 600:
                return str(code)
    found = re.search(r"\b([45]\d\d)\b", str(error))
    return found.group(1) if found else type(error).__name__


def _guarded(name: str, runnable: Runnable) -> Runnable:
    """One model of the chain, with the rate-limit policy of classify_failure()."""
    shown = name.split(":", 1)[-1]

    def call(value, config):
        attempts = 0
        log = _attempt_log.get()
        while True:
            with _calls_lock:
                if name in _unavailable:
                    _calls[f"{name} skipped"] += 1
                    if log:
                        log(f"{shown} skipped ({_unavailable[name]} for this run)")
                    raise ModelSkipped(f"{name} unavailable for this run ({_unavailable[name]})")
            if log:
                log(f"trying {shown}...")
            start = time.monotonic()
            try:
                result = runnable.invoke(value, config)
            except Exception as error:
                kind, delay = classify_failure(error)
                took = f"after {time.monotonic() - start:.0f}s"
                if kind == "overloaded":
                    with _calls_lock:
                        _overloaded[name] += 1
                        if _overloaded[name] >= OVERLOADED_SKIP_AFTER:
                            _unavailable[name] = "overloaded"
                if kind in ("daily", "auth") or (kind == "unknown_quota" and attempts >= 1):
                    with _calls_lock:
                        _unavailable[name] = kind
                retries = RATE_LIMIT_RETRIES if kind == "per_minute" else 1
                wait = RATE_LIMIT_DEFAULT_WAIT if delay is None else delay
                if (kind in ("daily", "auth", "overloaded", "other") or name in _unavailable
                        or attempts >= retries or wait > RATE_LIMIT_MAX_WAIT):
                    if log:
                        log(f"{shown} failed ({_error_label(error)}) {took}, next model")
                    raise
                attempts += 1
                with _calls_lock:
                    _calls[f"{name} waited"] += 1
                if log:
                    log(f"{shown} rate limited ({_error_label(error)}), waiting {wait:.0f}s")
                _sleep(wait)
                continue
            if log:
                log(f"{shown} done in {time.monotonic() - start:.0f}s")
            return result

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


def _client(provider: str, model: str, think: bool | None = None, max_tokens: int | None = None,
            timeout: float | None = None):
    """think: reasoning of a local model (None: config.OLLAMA_THINK). max_tokens: limit of the
    generated tokens of a local model, reasoning included (None: no limit). timeout: seconds per
    request of a cloud model (None: the provider's default)."""
    counter = [_CallCounter(f"{provider}:{model}")]
    if provider == "gemini":
        return ChatGoogleGenerativeAI(model=model, google_api_key=os.environ["GEMINI_API_KEY"],
                                      timeout=timeout or GEMINI_TIMEOUT, max_retries=1, callbacks=counter)
    if provider == "mistral":
        return ChatMistralAI(model=model, mistral_api_key=os.environ["MISTRAL_API_KEY"], timeout=timeout or MISTRAL_TIMEOUT,
                             max_retries=1, temperature=0, callbacks=counter)
    if provider == "ollama":
        # Reasoning off by default (config.OLLAMA_THINK): slower, and not always compatible with structured output
        think = config.OLLAMA_THINK if think is None else think
        return ChatOllama(model=model, num_ctx=config.OLLAMA_NUM_CTX, temperature=0, reasoning=think,
                          num_predict=max_tokens, client_kwargs={"timeout": OLLAMA_TIMEOUT}, callbacks=counter)
    raise ValueError(f"Unknown LLM provider: {provider}")


# Optional providers: left out of the chain when their API key is not set (only its presence is checked)
OPTIONAL_KEYS = {"mistral": "MISTRAL_API_KEY"}


def llm_chain(chain: list[tuple[str, str, bool]] | None = None) -> list[tuple[str, str]]:
    """Enabled models of a chain (config.MODEL_CHAIN by default), or only one provider when LLM_ONLY
    is set (e.g. LLM_ONLY=ollama).

    An optional provider without its API key in the environment is left out.
    """
    only = os.environ.get("LLM_ONLY")
    found = [(p, m) for p, m, enabled in (config.MODEL_CHAIN if chain is None else chain)
             if enabled and (not only or p == only) and (p not in OPTIONAL_KEYS or os.environ.get(OPTIONAL_KEYS[p]))]
    if not found:
        raise ValueError(f"No model left in the chain for LLM_ONLY={only}")
    return found


def only_local_left(chain: list[tuple[str, str, bool]] | None = None) -> bool:
    """True when every cloud model of the chain (config.MODEL_CHAIN by default) is skipped for the
    rest of the run (daily quota spent, key refused): only local models can still answer."""
    with _calls_lock:
        return all(f"{p}:{m}" in _unavailable for p, m in llm_chain(chain) if p not in config.LOCAL_PROVIDERS)


@cache
def structured_llm(schema, models: tuple[tuple[str, str], ...] | None = None, timeout: float | None = None):
    """Models of the chain (or the given models), each returning the Pydantic schema, tried in
    order with the rate-limit policy. timeout: seconds per request of the cloud models (None: default)."""
    return _chain([(f"{provider}:{model}", (_client(provider, model, timeout=timeout) if timeout
                                            else _client(provider, model)).with_structured_output(schema))
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


class LocalCallFailed(Exception):
    """A local call that gave no usable answer: reason "timeout", "too long" or "error (...)"."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


_monotonic = time.monotonic     # replaced in tests


def local_call(messages: list, max_tokens: int, timeout: float, think: bool = False,
               schema: type | None = None, chain: list[tuple[str, str, bool]] | None = None) -> tuple[str, str]:
    """Text of the answer of the first local model of the chain that answers, and its name.

    chain: config.MATCH_CHAIN by default (personal data); a task on public data passes the local
    models of MODEL_CHAIN. Either one goes through local_models(): a cloud model stops the program.

    The answer is read as a stream, against a deadline checked at every piece: the timeout of the
    HTTP client only counts the time between two pieces, so a model that keeps reasoning never hit
    it. Past the deadline the stream is closed (Ollama stops generating) and the call fails with
    "timeout"; an answer cut by max_tokens (reasoning included) fails with "too long". Both end the
    call: the next model would take as long. Other errors pass to the next model of the chain.
    schema: a Pydantic model whose JSON schema constrains the answer (the caller validates it).
    """
    failure = LocalCallFailed("error (no model)")
    for provider, model in local_models(config.MATCH_CHAIN if chain is None else chain):
        name = f"{provider}:{model}"
        options = {"format": schema.model_json_schema()} if schema else {}
        deadline = _monotonic() + timeout
        parts, done_reason, stream = [], None, None
        try:
            stream = _client(provider, model, think, max_tokens).stream(messages, **options)
            for chunk in stream:
                if isinstance(chunk.content, str):
                    parts.append(chunk.content)
                done_reason = (chunk.response_metadata or {}).get("done_reason") or done_reason
                if _monotonic() > deadline:
                    raise LocalCallFailed("timeout")
        except LocalCallFailed:
            raise
        except Exception as error:      # any provider error; the type is kept so bugs stay visible
            failure = LocalCallFailed(f"error ({type(error).__name__})")
            continue
        finally:
            if stream is not None and hasattr(stream, "close"):
                stream.close()
        if done_reason == "length":
            raise LocalCallFailed("too long")
        return "".join(parts), name        # counted by the client's _CallCounter
    raise failure


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