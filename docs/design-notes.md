# Design notes

How things work and why they were built this way. Unordered notes, updated along the way.

## Configuration

- `job_watch/config.py`: technical settings (paths, models, web access), committed.
- `user_config.py`: personal settings (keywords, companies, aliases, company domains, scoring rules), not committed. Each user has their own; `user_config.example.py` is the template.
- `config.py` re-exports the personal settings, so the rest of the code only imports `config`. A missing `user_config.py` stops the program with a clear message; a missing variable raises an import error naming it.

## Project layout

- `job_watch/`: application code (package), split by feature: `offers/` (V1 pipeline), `registry/` (V1.1 career sites registry), `judges/` (LLM judges), `web/` (web access, browser, search). `config.py` and `llm.py` stay at the top level, shared by all.
- `main.py` and `scripts/`: entry points.
- Rule: the logic lives in `job_watch/`; scripts only call it (load the registry, loop, ask for confirmation, print) and never import another script. `evals/` holds evaluations that call a real LLM and cost API calls, unlike future unit tests.
- Everything runs from the project root (`python main.py`, `python -m scripts.<name>`, `python -m evals.<name>`), so imports work without `sys.path` changes.
- `tests/`: unit and end-to-end tests run with pytest, without LLM or network (`python -m pytest`). `tests/trap_site/` is a local trap website used to prove the browser guardrails.

## Filtering and scoring (V1)

- Funnel: cheap rules first (keywords, reject rules, score rules), LLM later on the remaining offers only.
- False negatives cost more than false positives: a rule only rejects obvious cases.
- German ads detected by the ratio of German stopwords (threshold 0.08, chosen from the observed distribution).
- SQLite with `INSERT OR IGNORE` on the link: an offer is stored once, later runs never overwrite it.

## Career sites registry (V1.1)

Goal: for each target company, find the URL of the page that lists its job offers (not just its career site), only where automated access is allowed. This URL is what V1.2 reads.

Why: the RSS feed is incomplete (no location, links that lead to the job list). Company career sites are the most reliable source, but their job list URL must be known first.

`data/career_sites.json` (not committed) is the registry itself: one entry per company, with its candidates, the chosen URL, its status and the trail of every decision.

How, in order:
1. `build_registry`, web search (Serper): finds where to go. One search per company missing from the registry. Only links allowed by robots.txt are kept as candidates. Existing entries are never overwritten.
2. `resolve_registry`, rules: proposes a job list URL. Rules are applied to the search candidates; when none matches, the company's own career pages are opened in a headless browser (Playwright) and the same rules are applied to their links (buttons, iframes, JavaScript content). Browser results are cached in `discovered`. Rules in `job_watch/registry/rules.py`.
3. `verify_registry`, LLM page judge: confirms or rejects. The judge reads the rendered page and says whether it actually lists job offers. If the rule URL is missing or rejected, the best candidates on the company's own domain are judged too. Logic in `job_watch/registry/verify.py`.

Serper and Playwright complement each other: Serper searches the whole web but only knows indexed pages; Playwright only opens a known URL but sees its full content. The rules are cheap and fast; the judge understands the content.

Rules (step 2):
- Platform rule: hosted on a known recruiting platform (Workday, Oracle, SuccessFactors, SmartRecruiters, Greenhouse, Taleo, Umantis, Personio).
- Job subdomain rule: `jobs.` / `careers.` subdomain whose domain matches the company.

Page judge (step 3):
- Classifies the page: `job_list`, `single_offer`, `search_form`, `overview`, `form`, `error`, `other`.
- When the page is not a job list, proposes the link most likely to lead to it; this link is followed (2 hops at most), each page checked against robots.txt first.
- Candidates are ranked by job-related words in their title and URL ("job", "offres", "postes"... count more than "career"); the 3 best are judged, the first job list wins.
- A URL already rejected is never judged again.

Status of an entry:
- `to_check`: not processed yet.
- `ok`: job list found, allowed, confirmed by the judge.
- `blocked`: job list found but forbidden by robots.txt or a blocked domain. Offers will come from e-mail alerts (V1.4).
- `not_found`: no job list among the URLs tried; `jobs_url` is cleared, the rejected URLs stay in the trail. Left to a later agent.

Temporary failures (page that does not load, robots.txt unreadable, LLM API unavailable) never produce a final status: the LLM call is retried 3 times with a 10 s wait, the entry is retried in a second pass at the end of the run, and only then saved as `not_found`, with the cause in the trail.

Matching a domain with a company:
- Accents and hyphens are removed on both sides ("Edmond de Rothschild" matches `edmond-de-rothschild.com`).
- Short names (under 5 characters) must start a domain label ("Syz" matches `syzgroup.com`); longer names may appear anywhere in it.
- `COMPANY_DOMAINS` in `user_config.py` declares domains that do not carry the name (`ge.ch` for État de Genève).

Other choices:
- Shortest path among matching links: usually the job list root, not a single offer.
- Greenhouse: a single offer URL is reduced to the company board (`/<company>`), because expired offers redirect to an error page.
- `resolved_by` records how the URL was found (`platform rule`, `browser + job subdomain rule`, `candidate judge`...). Entries edited by hand (no `resolved_by`) are never changed; entries verified by the judge are not recomputed by the rules.
- Aliases (`COMPANY_ALIASES`) avoid paying two searches for the same company.
- The browser only opens pages on the company's own domain (2 at most), once per company.
- `evals/check_page_judge.py` is the judge's test set: pages verified by hand, run again after any change to the judge or the browser.
- `scripts/show_registry.py` gives a read-only overview: status, URL, and whether it was confirmed by the judge.

Known limitations:
- Links followed by the judge are not checked against the company's domain, only the starting candidates are.
- A short name can match the start of an unrelated domain (`bcf` and `bcfcareer.nl`).
- The judge is not fully deterministic: the same page can get a different proposed link from one run to another.
- An empty job list ("no open positions") is classified as `overview` instead of being kept as a valid job list.
- Pages that need an action to show offers (a search button, as on Microsoft) are not handled.
- Some job lists cover more than the company (`jobs.admin.ch` for the Cyber-Defence Campus): V1.2 must filter offers by entity.
- All SuccessFactors career sites seen so far forbid robots (`Disallow: /`).

Found with a second company list (watchmakers, 41 companies: 14 ok, 1 blocked, 26 not_found):
- Wrong company accepted: a namesake domain passes `domain_matches` and the judge only checks the page type, not who owns it (`richemont.swiss`, a different organisation, accepted for Richemont).
- Anti-bot protection: many sites refuse headless browsers ("access denied", pages that never load: Swatch Group brands, Hublot, Zenith). Reported as `not_found` although the site was found; never bypassed.
- Short domains: the domain often carries a short form of the name (`patek.com`, `iwc.com`), which `domain_matches` does not accept.
- Tracking parameters (`?srsltid=...`) are kept in the saved URLs.
- Results depend on the sector: rules and test set were tuned on banks and security companies.

## Offer list agent (V1.2, in progress)

Goal: read every offer of a job list, whatever its pagination (numbered pages, "Next", "load more"), on any site.

Why an agent: the registry rules (URL patterns, name matching, CSS selectors) were tuned on banks and failed on a second list (watchmakers). Recognising "the control that leads to the next page" is a question of meaning, so it is left to an LLM. The code provides the harness: tools, guardrails, budgets, validation and evaluation.

Principle: the agent decides, the code constrains. The LLM never handles URLs or selectors: it only picks the number of an element listed by the code, and the code refuses any action that is not allowed, whatever the LLM asked for (including under prompt injection).

Built so far (`job_watch/web/`):
- `session.py`, `BrowserSession`: one headless browser page kept open, in a disposable context (no account, downloads refused, popups closed). Every navigation is intercepted: GET only, same host as the start URL (`www.` ignored), robots.txt and blocked domains checked. Every event goes to a trail.
- `observe()`: the visible text and the clickable elements of the page, numbered by the code, with the facts the guardrails need (visible text, accessible name, link target, form, cookie banner, iframe). It also gives the text that is new since the previous observation (`new_content.py`), so that a click that brings nothing can stop the agent, and only new content is sent to the LLM.
- `click(element_id, purpose)`: purpose is `pagination`, `cookie_refusal` or `cookie_acceptance`. Before clicking, the code checks: the number comes from the last observation, the click budget, the rules of `click_rules.py`, and that the element has not changed since it was observed (protection against a page swapping a button between check and use). Never a forced click.
- `click_rules.py`: pure rules, testable without a browser. Only links and buttons; never in a form with fields; forbidden actions refused in EN/FR/DE/IT (apply, sign in, register, save, subscribe, submit...); no link to another host, no download, no new tab; no sort, filter or search (they change the scope of the list).
- Cookie banners: refusal first. Acceptance is allowed only as a fallback, decided by the code (never by the agent or the page), when the refusal breaks access to the list (redirect, banner coming back), only inside a cookie banner, and always logged. Preferences are never opened. The browser context is disposable, so accepted cookies only follow an anonymous robot.

Tests:
- `tests/test_click_rules.py`: the rules on real controls collected on BCN, UBS, Lombard Odier, Rolex and ICRC, plus synthetic traps (a "Next" button whose accessible name is "Apply now", a login form whose button is "Next").
- `tests/trap_site/` + `tests/test_session_trap.py`: a local website full of traps (prompt injection in the text, Apply and Sign in buttons, "Next" links to another host or to a robots.txt-forbidden path, POST form, popup, covered button, cookie banner that breaks the list, banner in an iframe). After each test, the server log must show only GET requests, no trap page and no other host: "forbidden actions executed = 0". Disabling a guardrail makes tests fail.

Evaluation (`evals/check_list_agent.py`, cases in `evals/cases/list_agent.json`): 12 job lists checked by hand (6 banks and security, 6 watchmakers), with the total announced by the page and sample titles, some beyond page 1. Baseline with the previous extractor (page 1 only): 100 % on single-page lists, 8 to 38 % on paginated lists. The agent will be measured on the same cases.

Next: offer extraction on each observation (outside the agent conversation), then the comparison with the baseline.

Known limitations:
- The LLM can skip or repeat a page, and its stop reason is not reliable: the judge checks the total announced by the page.
- A cookie banner that is part of the page flow (not a floating dialog) is not detected, so its buttons are refused.
- At most 3000 elements are collected per observation; the agent sees only those from the first new or changed one.
- On a growing list whose pagination sits above the offers and never changes, that pagination is hidden from the agent.
- The new text sent to the agent is cut at 30000 characters.
- The forbidden-action words cover four languages; other languages rely on the other guardrails (forms, navigation interception).

## LLM usage

- One shared cloud client (`job_watch/llm.py`, Gemini), created on first use so that importing a module never requires the API key.
- Allowed because it only sees public data (web pages, search results, public offers). Personal documents never go to a cloud model.
- Web content is untrusted (prompt injection): placed between tags, the model is told never to follow instructions found there.
- "The prompt guides, the code constrains": links proposed by the model must come from the page or the search results, otherwise they are dropped.
- Structured output with Pydantic schemas: answers are typed and checked in code.
- Two judges: `page_judge` (is this page a job list?, V1.1) and `offer_judge` (does this offer still exist?, V1.3).
- LLM chain (`LLM_CHAIN` in `config.py`): Gemini models first, local `qwen3:8b` (Ollama) as last resort when the cloud is overloaded. `LLM_ONLY=ollama` runs a script with the local model only.
- Local model measured with the judge eval: 9/10, but it can wrongly answer `owner=no` (stops link following) and infer missing locations. Good enough for extraction, weaker as a judge.

## Web access and security

- `robots_status` returns `allowed`, `disallowed` (blocked domain or robots.txt rule) or `error` (robots.txt unreadable). `can_fetch` only accepts `allowed`. An error is never turned into a final `blocked`.
- robots.txt is downloaded once per site and per run (cache); failures are not cached, so they are retried.
- A missing robots.txt (404) means allowed.
- `BLOCKED_DOMAINS` overrides robots.txt for sites whose terms forbid automated access (jobs.ch, jobup.ch, LinkedIn, Indeed...). Their offers come from official e-mail alerts only.
- Honest user agent, low volume, no evasion of protections.
- Playwright preferred over Selenium: modern, waits automatically for page elements. Pages are rendered after `DOMContentLoaded` plus a short wait: the `load` event waits for every resource and timed out on heavy pages that were already usable (Oracle EU cloud).

## Verification agent (planned V1.3)

- Web content is untrusted, the model must answer "unknown" when unsure.
- The official link must come from the search results, `same_offer` / `still_open` are only trusted on a real job posting page.
- Serper budget: only offers above `MIN_VERIFY_SCORE`, at most `MAX_VERIFY_PER_RUN` per run, each offer verified once.
- Separation: the verification agent reads the web but has no personal documents; the matching agent (V2) has the personal documents but no web access and no tools.