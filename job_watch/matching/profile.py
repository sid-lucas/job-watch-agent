"""The candidate profile (config.PROFILE_PATH, Markdown): personal data, read only at run time.

The only reader of the file. It checks the matching chain first: the profile is never read while
a cloud model could receive it.
"""
from job_watch import config
from job_watch.llm import local_models


def read_profile() -> str:
    """Text of the profile; stops the program if MATCH_CHAIN holds a cloud model or the file is missing."""
    local_models(config.MATCH_CHAIN)
    if not config.PROFILE_PATH.is_file():
        raise SystemExit(f"Missing profile: {config.PROFILE_PATH} (see tests/fixtures/profile_example.md)")
    return config.PROFILE_PATH.read_text(encoding="utf-8")
