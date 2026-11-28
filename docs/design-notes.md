# Design notes

How things work and why they were built this way. Unordered notes, updated along the way.

## Configuration

- `job_watch/config.py`: technical settings (paths, models, web access), committed.
- `user_config.py`: personal settings (`COMPANIES` with their tier, aliases, domains and context; profile, criteria, kept triage domains, RSS feeds with a domain-triage flag each), not committed. Each user has their own; `user_config.example.py` is the template.
- `config.py` re-exports the personal settings, so the rest of the code only imports `config`. A missing `user_config.py` stops the program with a clear message; a missing variable raises an import error naming it. `PROFILE`, `CRITERIA`, `CODE_CRITERIA`, `KEPT_DOMAINS`, `RSS_FEEDS` and `COMPANIES` are validated at import (`offers/criteria.py`, Pydantic): missing "ask", both "reject" and "points", "group" or "absence" on a reject criterion, a "label" over 50 characters, unknown key or code criterion type, the same question twice, an unknown triage domain, a name or alias shared by two companies, a `company_tier` tier that no company has; each problem is one line naming the criterion or the company.

## Project layout

- `job_watch/`: application code (package), split by feature: `offers/` (V1 pipeline), `registry/` (V1.1 career sites registry), `judges/` (LLM judges), `web/` (web access, browser, search). `config.py` and `llm.py` stay at the top level, shared by all.
- `main.py` and `scripts/`: entry points.
- Rule: the logic lives in `job_watch/`; scripts only call it (load the registry, loop, ask for confirmation, print) and never import another script. `evals/` holds evaluations that call a real LLM and cost API calls, unlike future unit tests.
- Everything runs from the project root (`python main.py`, `python -m scripts.<name>`, `python -m evals.<name>`), so imports work without `sys.path` changes.
- `tests/`: unit and end-to-end tests run with pytest, without LLM or network (`python -m pytest`). `tests/trap_site/` is a local trap website used to prove the browser guardrails.

## Criteria and score

Principle: the LLM states what the ad says, the code decides. The user writes plain questions (`CRITERIA` in `user_config.py`), each one rejecting the offer or giving points; the LLM answers them, the code checks the answers and computes the score. The LLM never sees the points, the groups nor which criteria reject.
- Triage first (`offers/triage.py`): one domain of a closed list per offer, from title, location and company, in batches (cheap). Offers outside `KEPT_DOMAINS` are set aside without any criteria call. An offer without a valid answer has no domain and is kept.
- Criteria (`offers/ask_criteria.py`): one LLM call per offer answers every question with yes / no / unknown and a quote of the offer. The answer schema is built from the settings: one required field per criterion (c1, c2...), so the model can neither skip a criterion nor invent one. The prompt gives a short profile (context only), the questions, then the offer between tags (untrusted, cannot close its tags). Rules of the prompt for a "yes": the quote alone proves it (numbers answered from the number quoted), the job and not the company, the words of the offer and not a description of it, one continuous piece of text.
- Checks in code (`offers/criteria.py`): a "yes" counts only when its quote is found in the text the model read (case, accents and whitespace ignored, 3 to 300 characters); otherwise it is unknown. A criterion marked `absence` (no quote can prove an absence) counts without quote only when the whole ad was read (offer page opened and not cut), and is dropped when another "yes" of its group holds. Unknown never rejects and never gives points.
- Score: any reject criterion answered yes rejects the offer; otherwise the sum of the points of the "yes" criteria, only the best one per group. Code criteria (`CODE_CRITERIA`: company in a list, posted more than N days ago) need no LLM. Each reason shows a short label of the criterion and its quote.
- Where it runs: on the listing data for new career-site offers (a reject sets the offer aside before its page is opened), again on the page text when the page is read (these answers win), on the feed description for new RSS offers (not known to be the whole ad: absence criteria never count there).
- Stored: the raw answers with the fingerprint of the questions, the model that answered and whether the text was the whole ad (`offers`, and `listed_offers` for the listing). `scripts/rescore.py` checks them again and recomputes every score without LLM after a change of points, groups, code criteria, kept domains or checks; answers given to other questions are not used, and `--ask` asks those offers again (one call each, counted first with `--ask --dry-run`).
- Rejected offers stay in the database with their reasons (`offers.status`, `listed_offers.reject_reason`).
- SQLite, primary key (company, key): an offer is stored once, later runs never overwrite it (except rescore).
- Limits: the quote check proves that the text exists, not that it supports the answer (a model can answer "at least 5 years" with a quote saying 3); the prompt rules reduce it, the rescore makes it cheap to measure. A "yes" quoting an injection in the page passes the check (it is in the page); a "no" to a reject criterion cannot be checked and counts as unknown.

## Career sites registry (V1.1)

Goal: for each target company, find the URL of the page that lists its job offers (not just its career site), only where automated access is allowed. This URL is what V1.2 reads.

Why: the RSS feed is incomplete (no location, links that lead to the job list). Its descriptions start with a salary line added by the job board ("Salary: CHF ... per year", an estimate, not the employer's): it is removed when the feed is read, so the salary criteria only read what the employer writes. Company career sites are the most reliable source, but their job list URL must be known first.

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
- `"domains"` of a company in `COMPANIES` (`user_config.py`) declares domains that do not carry the name (`ge.ch` for État de Genève).

Other choices:
- Shortest path among matching links: usually the job list root, not a single offer.
- Greenhouse: a single offer URL is reduced to the company board (`/<company>`), because expired offers redirect to an error page.
- `resolved_by` records how the URL was found (`platform rule`, `browser + job subdomain rule`, `candidate judge`...). Entries edited by hand (no `resolved_by`) are never changed; entries verified by the judge are not recomputed by the rules.
- Every company of `COMPANIES` is a target; its `"aliases"` avoid paying two searches for the same company, `"context"` helps the page judge when the name is shared, and `"tier"` gives points through the `company_tier` code criteria.
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

## Career sites: list agent, extraction, detail (V1.2, in progress)

Goal: read every offer of a job list, whatever its pagination (numbered pages, "Next", "load more"), on any site.

Why an agent: the registry rules (URL patterns, name matching, CSS selectors) were tuned on banks and failed on a second list (watchmakers). Recognising "the control that leads to the next page" is a question of meaning, so it is left to an LLM. The code provides the harness: tools, guardrails, budgets, validation and evaluation.

Principle: the agent decides, the code constrains. The LLM never handles URLs or selectors: it only picks the number of an element listed by the code, and the code refuses any action that is not allowed, whatever the LLM asked for (including under prompt injection).

Built so far (`job_watch/web/`):
- `session.py`, `BrowserSession`: one headless browser page kept open, in a disposable context (no account, downloads refused, popups closed). Every navigation is intercepted: GET only, same host as the start URL (`www.` ignored), robots.txt and blocked domains checked. Every event goes to a trail.
- `observe()`: the visible text and the clickable elements of the page, numbered by the code, with the facts the guardrails need (visible text, accessible name, link target, form, cookie banner, iframe). It also gives the text that is new since the previous observation (`new_content.py`), so that a click that brings nothing can stop the agent, and only new content is sent to the LLM.
- `click(element_id, purpose)`: purpose is `pagination`, `cookie_refusal` or `cookie_acceptance`. Before clicking, the code checks: the number comes from the last observation, the click budget, the rules of `click_rules.py`, and that the element has not changed since it was observed (protection against a page swapping a button between check and use). Never a forced click.
- `click_rules.py`: pure rules, testable without a browser. Only links and buttons; never in a form with fields; forbidden actions refused in EN/FR/DE/IT (apply, sign in, register, save, subscribe, submit...); no link to another host, no download, no new tab; no sort, filter or search (they change the scope of the list).
- Offer links (extraction and detail phase): kept only on the same registrable domain (eTLD+1, public suffix list shipped with `tldextract`, private suffixes included, no network access) as the list page, because an applicant tracking system may list on one subdomain and show offers on another (`careers.` and `jobs.smartrecruiters.com`). Clicks and the browser guard keep the exact host; robots.txt and blocked domains apply to every page opened.
- Cookie banners: refusal first. Acceptance is allowed only as a fallback, decided by the code (never by the agent or the page), when the refusal breaks access to the list (redirect, banner coming back), only inside a cookie banner, and always logged. Preferences are never opened. The browser context is disposable, so accepted cookies only follow an anonymous robot.

Tests:
- `tests/test_click_rules.py`: the rules on real controls collected on BCN, UBS, Lombard Odier, Rolex and ICRC, plus synthetic traps (a "Next" button whose accessible name is "Apply now", a login form whose button is "Next").
- `tests/trap_site/` + `tests/test_session_trap.py`: a local website full of traps (prompt injection in the text, Apply and Sign in buttons, "Next" links to another host or to a robots.txt-forbidden path, POST form, popup, covered button, cookie banner that breaks the list, banner in an iframe). After each test, the server log must show only GET requests, no trap page and no other host: "forbidden actions executed = 0". Disabling a guardrail makes tests fail.

Evaluation (`evals/check_list_agent.py`, cases in `evals/cases/list_agent.json`): 12 job lists checked by hand (6 banks and security, 6 watchmakers), with the total announced by the page and sample titles, some beyond page 1. Baseline measured with the former single-page extractor (removed since): 100 % on single-page lists, 8 to 38 % on paginated lists. The agent is measured on the same cases.

Pipeline (`main.py`, node `fetch_career_sites` in the V1 graph, after `fetch_rss`), per registry company with status `ok`:
1. Navigation: the list agent walks the pages (above). Budgets in code (`config.py`), whatever the agent decides: at most `AGENT_MAX_LLM_CALLS` agent turns (stop `llm_budget`), and a stop after `AGENT_MAX_CLICKS_WITHOUT_NEW_CONTENT` pagination clicks in a row whose observation brings no line seen in no earlier observation of the run (stop `no_new_content`: going back and forth between pages already read counts as nothing new). LangGraph's `recursion_limit` stays above them as a safety net.
2. Extraction, triggered by the code on every observation with new text, outside the agent conversation: full new text cut into overlapping chunks, one structured LLM call per chunk. Checks in code: title found in the chunk (exact page text kept), location and reference found or emptied, link only if it is the href of an element of the observation on the list's registrable domain; "verified" when that element's text or name contains the title. Offer key: reference with a digit, else verified link, else hash of title and location; copies merged, two different titles never.
3. `listed_offers` (primary key company, key): every offer seen, first_seen / last_seen, kept by the filter or not. Written by `save_results` in the same transaction as `offers`, at the end of the run: an offer is never marked as seen without being stored.
4. Triage of the new offers (title, location, company; `MODEL_CHAIN`, cloud models first; batch size per model, `TRIAGE_BATCH_SIZE`): one of 10 domains (closed list with a short description each, `offers/criteria.py`), checked in code. "Other" only when the title gives no clue. When in doubt between Technology/IT and another domain, the LLM is told to choose Technology/IT. Then the criteria on the listing data for the offers whose domain is kept (see "Criteria and score"): a reject sets the offer aside.
5. Detail phase on the new offers kept: own link on the list's domain, not shared by other offers, at most `MAX_DETAIL_PAGES`, a pause between pages; one observation per page, no click; the page is accepted only if it contains the title (a label of the list such as "New" at its end is tolerated). The criteria are asked again on the page text. Raw page text kept as the description.
6. Score and storage: duplicates, the criteria of every offer (RSS offers are asked here), table `offers` (primary key company, key; RSS key `url:<link>`; older tables are migrated in place), display with the reasons and their quotes; the offers rejected by a criterion on the whole ad are listed by company (title | criterion | quote), like those set aside at the listing. An offer without detail keeps the answers on the listing data.
A company that fails is logged and skipped.

Known limitations:
- The LLM can skip or repeat a page, and its stop reason is not reliable: the judge checks the total announced by the page.
- A cookie banner that is part of the page flow (not a floating dialog) is not detected, so its buttons are refused.
- At most 3000 elements are collected per observation; the agent sees only those from the first new or changed one.
- On a growing list whose pagination sits above the offers and never changes, that pagination is hidden from the agent.
- The new text sent to the agent is cut at 30000 characters.
- A small local model misses IT offers with ambiguous titles (Business Analyst, ERP engineer, IT controller): false negatives, the most costly error of the funnel. The chain starts with cloud models, and the titles set aside are listed at the end of each run.
- Titles: labels that a list adds next to a title (New, Hot, Urgent...) are left out by the extraction prompt and by the code (general words, at the end of the title only).
- An offer stays in the database when it leaves the list: nothing marks it as closed yet.
- The forbidden-action words cover four languages; other languages rely on the other guardrails (forms, navigation interception).
- On a shared applicant tracking system domain, an offer link to another company on the same domain is accepted; the detail page must still contain the offer title.
- A listed offer that a changed criterion keeps again has no detail (it was set aside before the detail phase) and, being known, no run opens it: `scripts.rescore --open-details` opens these pages with the detail phase of a run (same guardrails, `MAX_DETAIL_PAGES` per company; those over the budget wait for the next call), asks the criteria on the whole ad and stores them in `offers`; `--dry-run` gives the pages and calls first.
- Publication date of career-site offers: read by the code from the first relative date of the page ("Posted 3 Days Ago", "il y a 3 jours", "vor 3 Tagen", today / yesterday; `offers/dates.py`), counted back from the day the page was read. An absolute date on the page is not read, and an open bound ("30+ Days Ago") gives no date: the offer then gets no "posted over N days ago" penalty. When the page shows other offers above the offer's own date, their date is taken.

## LLM usage

- One shared cloud client (`job_watch/llm.py`, Gemini), created on first use so that importing a module never requires the API key.
- Allowed because it only sees public data (web pages, search results, public offers). Personal documents never go to a cloud model.
- Web content is untrusted (prompt injection): placed between tags, the model is told never to follow instructions found there.
- "The prompt guides, the code constrains": links proposed by the model must come from the page or the search results, otherwise they are dropped.
- Structured output with Pydantic schemas: answers are typed and checked in code.
- One judge: `page_judge` (is this page a job list?, V1.1). The judge of the verification agent (does this offer still exist?) comes with V1.3.
- LLM chain (`MODEL_CHAIN` in `config.py`): one ordered list for every task (triage, list extraction, list agent, criteria, page judge), the first model is the preferred one; each entry can be disabled. Free tiers only: Gemini models first, local `qwen3:8b` (Ollama) as last resort. Mistral stays supported in code but is disabled (its free tier is not active: 402). A model is enabled only after `scripts/check_model.py` confirmed structured output and tool calling on it. `LLM_ONLY=ollama` runs a script with the local model only. Timeouts per request: 30 s Gemini, 60 s Mistral, 180 s Ollama (last model, slow on long pages).
- Quotas are per model and per project on the Gemini API: a few hundred requests a day for the lite models, about twenty for the larger ones. A long run (a new database, many companies) can spend them all, and then only the local model is left.
- Rate limits, read from the error (shared LangChain error classes; Google `quotaId` and `retryDelay`, HTTP `Retry-After`): a per-minute limit (requests or tokens) waits the given delay (at most 60 s) and retries the same model twice; a daily or monthly quota, a refused key (401, 403) or a payment required (402) skips the model for the rest of the run; a 429 that cannot be read is retried once after a short wait, then the model is skipped. Other errors only pass this call to the next model. Calls answered, failed, waited and skipped are counted per model and reported by the evals.
- Triage batch size follows the model that answers (`TRIAGE_BATCH_SIZE`, by model, else by provider): a model with a small tokens-per-minute limit gets smaller batches.
- When only local models are left for the run, at most `LOCAL_ONLY_MAX_CRITERIA` offers are still answered by the criteria; the others are deferred: not stored (RSS offers, listed offers, offer pages), so they stay new and are asked on the next run. The local model is slower and weaker on the criteria; mixing a few of its answers is accepted. Each offer asked prints one line (progress, model, duration).
- Local model measured with the judge eval: 9/10, but it can wrongly answer `owner=no` (stops link following) and infer missing locations. Good enough for extraction, weaker as a judge.

## Matching against the profile (step 2, in progress)

- Question of step 1: does the offer suit me (criteria, score)? Question of step 2: does the offer want me? The score of step 1 is never changed by the matching.
- Personal data: the profile is one Markdown file, `PROFILE_PATH` (`data/personal/profile.md`, not committed), read only at run time by `matching/profile.py`. Every task that receives it uses `MATCH_CHAIN`, which may only hold local models: `llm.local_models()` stops the program if it names a cloud model, even a disabled one. `tests/fixtures/profile_example.md` is a fictitious profile in the same format, for the tests.
- Brick 1, requirements of an ad (`matching/requirements.py`, no personal data): each requirement is one thing, with an exact quote of the ad (checked in code as for the criteria), a kind (must, nice), a category from a fixed list and a short label. Company presentation and benefits are ignored. Same local chain as the rest of the matching.
- Reasoning (`MATCH_THINK`): qwen3 with reasoning and structured output in one call gave unstable lists (empty once, requirements merged). So one call reasons in free text and writes a draft, a second call without reasoning puts the draft in the schema; the draft is treated as untrusted too. About 25 s per offer instead of 3 s, with requirements better split.
- Next bricks: each requirement against the profile (covered, partial, missing, with a checked quote of the profile and its level), a match score computed in code, stored in `offers`.

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
- Serper budget: only offers above a score threshold, at most a few per run, each offer verified once (settings added with V1.3).
- Separation: the verification agent reads the web but has no personal documents; the matching agent (V2) has the personal documents but no web access and no tools.