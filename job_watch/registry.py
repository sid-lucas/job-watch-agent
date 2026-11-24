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