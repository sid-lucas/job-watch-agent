"""Shared LLM access for public web data: cloud models first, a local model as last resort.
Personal documents are never sent through this module."""
import logging
import os
import threading
import time
from collections import Counter
from functools import cache

from dotenv import load_dotenv
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama

from job_watch import config

load_dotenv()

GEMINI_TIMEOUT = 30     # seconds per request; an overloaded cloud model is replaced by the next one in the chain
OLLAMA_TIMEOUT = 180    # seconds per request; the local model is the last one, and slow on a long page


class _UnsupportedSchemaKey(logging.Filter):
    """Drop the 'Key ... is not supported in schema, ignoring' warning of langchain_google_genai.

    Gemini ignores keys such as additionalProperties (extra="forbid"): the code validates every
    answer again, so the warning carries no information. Other warnings of that logger stay.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return "is not supported in schema" not in record.getMessage()


logging.getLogger("langchain_google_genai._function_utils").addFilter(_UnsupportedSchemaKey())


_calls: Counter[str] = Counter()     # "provider:model" -> answers, "... failed" -> errors, "... skipped"
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
            if _is_quota_error(error):
                _out_of_quota.add(self.name)


# Models that answered with a quota error (HTTP 429): skipped for the rest of the process, so
# each call goes straight to the next model of the chain instead of waiting for a new refusal
_out_of_quota: set[str] = set()


class ModelSkipped(Exception):
    """Raised instead of calling a model already out of quota; the fallback takes the call."""


def _is_quota_error(error: BaseException) -> bool:
    text = str(error)
    return getattr(error, "code", None) == 429 or "429" in text or "RESOURCE_EXHAUSTED" in text


def _skip_if_out_of_quota(name: str):
    def check(value):
        with _calls_lock:
            if name in _out_of_quota:
                _calls[f"{name} skipped"] += 1
                raise ModelSkipped(f"{name} is out of quota for this run")
        return value
    return RunnableLambda(check, name=f"skip_if_out_of_quota[{name}]")


def _chain(runnables: list) -> Runnable:
    """Models in order, each skipped once it is out of quota, with fallbacks to the next ones."""
    guarded = [_skip_if_out_of_quota(name) | runnable for name, runnable in runnables]
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


def _client(provider: str, model: str):
    counter = [_CallCounter(f"{provider}:{model}")]
    if provider == "gemini":
        return ChatGoogleGenerativeAI(model=model, google_api_key=os.environ["GEMINI_API_KEY"],
                                      timeout=GEMINI_TIMEOUT, max_retries=1, callbacks=counter)
    if provider == "ollama":
        # Reasoning disabled: not supported together with structured output
        return ChatOllama(model=model, num_ctx=config.OLLAMA_NUM_CTX, temperature=0, reasoning=False,
                          client_kwargs={"timeout": OLLAMA_TIMEOUT}, callbacks=counter)
    raise ValueError(f"Unknown LLM provider: {provider}")


def llm_chain() -> list[tuple[str, str]]:
    """LLM_CHAIN from config, or only one provider when LLM_ONLY is set (e.g. LLM_ONLY=ollama)."""
    only = os.environ.get("LLM_ONLY")
    chain = [(p, m) for p, m in config.LLM_CHAIN if not only or p == only]
    if not chain:
        raise ValueError(f"No model left in LLM_CHAIN for LLM_ONLY={only}")
    return chain


@cache
def structured_llm(schema):
    """Models of the chain, each returning the given Pydantic schema, tried in order (a model out of
    quota is skipped)."""
    return _chain([(f"{provider}:{model}", _client(provider, model).with_structured_output(schema))
                   for provider, model in llm_chain()])



@cache
def tool_llm(tools: tuple):
    """Models of the chain, each bound to the given tools, tried in order.

    Binding is done per model before the fallbacks are chained: a fallback model receives
    the same tool schemas. The answer is an AIMessage; its tool_calls are requests only.
    """
    return _chain([(f"{provider}:{model}", _client(provider, model).bind_tools(list(tools)))
                   for provider, model in llm_chain()])


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