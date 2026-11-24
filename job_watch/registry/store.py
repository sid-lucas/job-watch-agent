"""Career sites registry: load, save and platform detection."""
import json
from urllib.parse import urlsplit

from job_watch import config

PLATFORMS = {
    "myworkdayjobs.com": "workday",
    "oraclecloud.com": "oracle",
    "oraclecloud.eu": "oracle",
    "smartrecruiters.com": "smartrecruiters",
    "greenhouse.io": "greenhouse",
    "taleo.net": "taleo",
    "umantis.com": "umantis",
    "successfactors.com": "successfactors",
    "successfactors.eu": "successfactors",
    "personio.com": "personio",
}


def detect_platform(url: str) -> str | None:
    domain = urlsplit(url).netloc.lower()
    for suffix, platform in PLATFORMS.items():
        if domain == suffix or domain.endswith("." + suffix):
            return platform
    return None


def load_registry() -> dict:
    if config.REGISTRY_PATH.exists():
        return json.loads(config.REGISTRY_PATH.read_text(encoding="utf-8"))
    return {}


def save_registry(registry: dict) -> None:
    # Write to a temporary file first so an interruption never corrupts the registry
    tmp = config.REGISTRY_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(config.REGISTRY_PATH)


def job_list_root(url: str, platform: str | None) -> str:
    """Return the job list root for platforms where a single offer URL contains it."""
    parts = urlsplit(url)
    if platform == "greenhouse":
        # job-boards.eu.greenhouse.io/<company>/jobs/<id> -> job-boards.eu.greenhouse.io/<company>
        segments = [s for s in parts.path.split("/") if s]
        if segments:
            return f"{parts.scheme}://{parts.netloc}/{segments[0]}"
    return url