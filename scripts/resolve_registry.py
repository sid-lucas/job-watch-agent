"""Choose the job list URL of each registry entry automatically.

Entries with status "to_check" and entries already resolved by a rule are (re)computed.
Entries edited by hand (no "resolved_by") are never changed.
Rules, in order of confidence:
1. a candidate hosted on a known recruiting platform
2. a jobs/careers subdomain whose domain matches the company name
If no search candidate matches, the company's own career pages are opened in a headless
browser and the same rules are applied to their links (cached in "discovered").
A job list found but forbidden by robots.txt gets status "blocked".
"""
from job_watch.web import access as web
from job_watch.registry.rules import browse, resolve
from job_watch.registry.store import job_list_root, load_registry, save_registry


def main():
    registry = load_registry()

    for company, entry in registry.items():
        if entry["status"] != "to_check" and "resolved_by" not in entry:
            continue    # edited by hand
        if "verified" in entry:
            continue    # decided by the page judge (verify_registry)
        names = [company] + entry.get("aliases", [])

        result = resolve(entry["candidates"], names)
        prefix = ""
        if not result:
            if "discovered" not in entry:
                print(f"Browsing {company}...")
                entry["discovered"] = browse(entry, names)
                save_registry(registry)     # browsing is slow: keep the result even if interrupted
            result = resolve(entry["discovered"], names)
            prefix = "browser + "
        if not result:
            continue

        candidate, rule = result
        url = job_list_root(candidate["url"], candidate["platform"])
        if web.robots_status(url) != web.ALLOWED:
            url = candidate["url"]
        access = web.robots_status(url)
        if access == web.ERROR:
            print(f"RETRY     {company:26} robots.txt unreadable, retried on next run")
            continue    # temporary: nothing saved for this entry
        entry["jobs_url"] = url
        entry["platform"] = candidate["platform"]
        entry["status"] = "ok" if access == web.ALLOWED else "blocked"
        entry["resolved_by"] = prefix + rule

    save_registry(registry)

    for status in ("ok", "blocked", "not_found"):
        companies = [c for c, e in registry.items() if e["status"] == status]
        print(f"\n{status.upper()} ({len(companies)})")
        for company in companies:
            entry = registry[company]
            print(f"  {company:26} {entry.get('resolved_by', 'manual'):30} {entry['jobs_url'] or '(no job list)'}")
    pending = [c for c, e in registry.items() if e["status"] == "to_check"]
    print(f"\nTO_CHECK ({len(pending)}):", ", ".join(pending))


if __name__ == "__main__":
    main()