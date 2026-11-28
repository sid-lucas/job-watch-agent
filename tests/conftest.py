"""Test session setup: the real data/ directory is out of reach of every test.

config.DB_PATH and config.REGISTRY_PATH point to a temporary directory from the start of the
session, before any monkeypatch: restoring a patched value (monkeypatch.undo()) can only lead
back to these temporary paths, never to data/.
"""
import tempfile
from pathlib import Path

import pytest

from job_watch import config

_SESSION_DIR = Path(tempfile.mkdtemp(prefix="job-watch-tests-"))
_REAL_DATA = config.BASE_DIR / "data"
config.DB_PATH = _SESSION_DIR / "offers.db"
config.REGISTRY_PATH = _SESSION_DIR / "career_sites.json"


@pytest.fixture(autouse=True)
def data_stays_out_of_reach():
    yield
    for path in (config.DB_PATH, config.REGISTRY_PATH):
        assert _REAL_DATA not in Path(path).resolve().parents, f"a test left a path in data/: {path}"


@pytest.fixture(autouse=True)
def no_real_llm(request, monkeypatch):
    """Tests never call a real model: building an LLM client fails, unless the test is marked
    allow_llm_client (it only builds a client, never calls it). Cached chains are cleared."""
    from job_watch import llm
    llm.structured_llm.cache_clear()
    llm.tool_llm.cache_clear()
    llm._local_chain.cache_clear()
    if request.node.get_closest_marker("allow_llm_client") is None:
        def refuse(provider, model, think=None):
            raise RuntimeError(f"a test tried to build a real LLM client ({provider}:{model}): use a fake")
        monkeypatch.setattr(llm, "_client", refuse)
    yield
    llm.structured_llm.cache_clear()
    llm.tool_llm.cache_clear()
    llm._local_chain.cache_clear()
