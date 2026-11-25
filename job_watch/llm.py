"""Shared LLM access for public web data: cloud models first, a local model as last resort.
Personal documents are never sent through this module."""
import os
import time
from functools import cache

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama

from job_watch import config

load_dotenv()

GEMINI_TIMEOUT = 30     # seconds; an overloaded cloud model is replaced by the next one in the chain


def _client(provider: str, model: str):
    if provider == "gemini":
        return ChatGoogleGenerativeAI(model=model, google_api_key=os.environ["GEMINI_API_KEY"],
                                      timeout=GEMINI_TIMEOUT, max_retries=1)
    if provider == "ollama":
        # Reasoning disabled: not supported together with structured output
        return ChatOllama(model=model, num_ctx=config.OLLAMA_NUM_CTX, temperature=0, reasoning=False)
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
    """Models of the chain, each returning the given Pydantic schema, tried in order."""
    runnables = [_client(provider, model).with_structured_output(schema) for provider, model in llm_chain()]
    return runnables[0].with_fallbacks(runnables[1:]) if len(runnables) > 1 else runnables[0]



def tool_llm(tools: tuple):
    """Models of the chain, each bound to the given tools, tried in order.

    Binding is done per model before the fallbacks are chained: a fallback model receives
    the same tool schemas. The answer is an AIMessage; its tool_calls are requests only.
    """
    runnables = [_client(provider, model).bind_tools(list(tools)) for provider, model in llm_chain()]
    return runnables[0].with_fallbacks(runnables[1:]) if len(runnables) > 1 else runnables[0]


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