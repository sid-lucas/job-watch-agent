# Design notes

How things work and why they were built this way. Unordered notes, updated along the way.

## Configuration

- `job_watch/config.py`: technical settings (paths, models, web access), committed.
- `user_config.py`: personal settings (keywords, companies, aliases, scoring rules), not committed. Each user has their own; `user_config.example.py` is the template.
- `config.py` re-exports the personal settings, so the rest of the code only imports `config`.

## Project layout

- `job_watch/`: application code (package). `main.py` and `scripts/`: entry points.
- Everything runs from the project root (`python main.py`, `python -m scripts.<name>`), so imports work without `sys.path` changes.

## Filtering and scoring (V1)

- Funnel: cheap rules first (keywords, reject rules, score rules), LLM later on the remaining offers only.
- False negatives cost more than false positives: a rule only rejects obvious cases.
- German ads detected by the ratio of German stopwords (threshold 0.08, chosen from the observed distribution).
- SQLite with `INSERT OR IGNORE` on the link: an offer is stored once, later runs never overwrite it.

## Career sites registry (V1.1)

Goal: for each target company, find the URL of the page that lists its job offers (not just its career site), only where automated access is allowed. This URL is what V1.2 reads.

Why: the RSS feed is incomplete (no location, links that lead to the job list). Company career sites are the most reliable source, but their job list URL must be known first.

How, in order:
1. `build_registry`, web search (Serper): finds where to go. One search per company missing from the registry gives its career pages. Only links allowed by robots.txt are kept as candidates. Existing entries are never overwritten.
2. `resolve_registry`, rules on the search candidates: a link on a known recruiting platform, or on a `jobs.` / `careers.` subdomain of the company, is taken as the job list.
3. `resolve_registry`, headless browser (Playwright): looks at what is on the page. When no search candidate matches, the company's own career pages are opened and the same rules are applied to their links (buttons, iframes, JavaScript content), e.g. the Pictet career page links to its SuccessFactors job list. Results are cached in `discovered`.

Serper and Playwright complement each other: Serper searches the whole web but only knows indexed pages; Playwright only opens a known URL but sees its full content.

Rules:
- Platform rule: hosted on a known recruiting platform (Workday, Oracle, SuccessFactors...). Most reliable.
- Job subdomain rule: `jobs.` / `careers.` subdomain whose domain matches the company name or an alias. Short names must match a whole domain label, to avoid noise.

Status of an entry: `to_check` (not resolved yet), `ok` (job list found and allowed), `blocked` (found but forbidden by robots.txt, planned), `none` (nothing reliable found, planned).

Other choices:
- Shortest path among matching links: usually the job list root, not a single offer.
- Greenhouse: a single offer URL is reduced to the company board (`/<company>`), because expired offers redirect to an error page.
- `resolved_by` records the rule used. Rule-based entries are recomputed on each run; entries edited by hand are never changed.
- Aliases (`COMPANY_ALIASES`) avoid paying two searches for the same company.
- The browser only opens pages on the company's own domain (2 at most), once per company.

## Web access and security

- robots.txt checked before every fetch, with a timeout. A missing robots.txt (404) means allowed; any other error means not allowed.
- `BLOCKED_DOMAINS` overrides robots.txt for sites whose terms forbid automated access (jobs.ch, jobup.ch, LinkedIn, Indeed...). Their offers come from official e-mail alerts only.
- Honest user agent, low volume, no evasion of protections.
- Playwright preferred over Selenium: modern, waits automatically for page elements.

## Verification agent (planned V1.3)

- Cloud LLM (Gemini) allowed because it only sees public data (offers, search results, web pages).
- Web content is untrusted: placed between tags, the model must answer "unknown" when unsure.
- "The prompt guides, the code constrains": the official link must come from the search results, `same_offer` / `still_open` are only trusted on a real job posting page.
- Serper budget: only offers above `MIN_VERIFY_SCORE`, at most `MAX_VERIFY_PER_RUN` per run, each offer verified once.
- Separation: the verification agent reads the web but has no personal documents; the matching agent (V2) has the personal documents but no web access and no tools.