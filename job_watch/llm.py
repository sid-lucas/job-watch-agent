"""Shared cloud LLM access. Only public web data is sent: never personal documents."""
import os
import time
from functools import cache

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_google_genai.chat_models import GoogleAPIError

from job_watch import config

load_dotenv()


def _client(model: str) -> ChatGoogleGenerativeAI:
    # One quick internal retry only: an overloaded model is replaced by the next one instead
    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=os.environ["GEMINI_API_KEY"],
        timeout=60,
        max_retries=1,
    )


@cache
def structured_llm(schema):
    """Main model with fallback models, all returning the given Pydantic schema."""
    models = [config.VERIFY_MODEL] + config.LLM_FALLBACK_MODELS
    runnables = [_client(model).with_structured_output(schema) for model in models]
    return runnables[0].with_fallbacks(runnables[1:])


def call_with_retry(func, *args, attempts: int = 2, wait_seconds: int = 5):
    """Call an LLM function, with one short retry. Return None if every model keeps failing:
    the caller then retries later instead of waiting."""
    for attempt in range(1, attempts + 1):
        try:
            return func(*args)
        except GoogleAPIError as error:
            print(f"          LLM error (all models), attempt {attempt}/{attempts}: {str(error)[:80]}")
            if attempt < attempts:
                time.sleep(wait_seconds)
    return None