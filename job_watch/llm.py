"""Shared cloud LLM client. Only public web data is sent: never personal documents."""
import os
from functools import cache

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

from job_watch import config

load_dotenv()


@cache
def get_llm() -> ChatGoogleGenerativeAI:
    """Create the client on first use only, so importing a module never requires the API key."""
    return ChatGoogleGenerativeAI(
        model=config.VERIFY_MODEL,
        google_api_key=os.environ["GEMINI_API_KEY"],
        timeout=60,
        max_retries=2,
    )