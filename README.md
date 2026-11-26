# job-watch

Job monitoring system for IT positions in Switzerland.
It collects job offers from authorized sources, filters and scores them against a candidate profile, and prepares application drafts for human review.

## Setup

```bash
git clone git@github.com:sid-lucas/job-watch-agent.git
cd job-watch-agent
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

Personal settings (target companies, aliases, company domains, dealbreakers and bonuses):

```bash
cp user_config.example.py user_config.py
```

Then edit `user_config.py`. This file is not committed: each user keeps their own.

API keys go in a `.env` file at the project root (not committed):

```
SERPER_API_KEY=...
GEMINI_API_KEY=...
MISTRAL_API_KEY=...     # optional: Mistral is skipped in the LLM chain without it
```

## Project structure

```
job_watch/              application code (package)
  offers/               V1 pipeline: RSS and career sites -> filter -> flags -> SQLite (offers, listed_offers)
  list_agent/           V1.2 career sites: list agent (LangGraph), offer extraction, detail phase
  registry/             V1.1 career sites registry (storage, resolution rules, verification)
  judges/               LLM judges (career pages, offers)
  web/                  web access (robots.txt, fetching), headless browser, web search
  config.py, llm.py     technical settings, shared LLM client
scripts/                entry points for registry building and maintenance, statistics
evals/                  evaluations that call a real LLM (page judge test set)
docs/                   design notes
data/                   local database and registry (not committed)
main.py                 entry point
user_config.example.py  template for personal settings
```

Run everything from the project root: `python main.py`, and `python -m scripts.<name>` for scripts.

How things work and why: see [docs/design-notes.md](docs/design-notes.md).

## Usage

```bash
python main.py                         # RSS and career sites: collect, filter, score, store, list the best new ones
python main.py --sources rss           # RSS feed only
python main.py --sources career_sites --companies "Lombard Odier,ICRC"   # some registry companies only
python main.py --db /tmp/try.db --registry /tmp/registry.json            # another database and registry
LLM_ONLY=ollama python main.py ...     # local model only (Gemini quota exhausted)
```

Career sites (V1.2): for each registry company with status `ok`, an LLM agent walks the job list
(pagination and cookie banners only, guardrails in code), the code extracts and checks the offers and
stores every listed offer in `listed_offers`. New offers are triaged (domain, kind of IT job), the
dealbreakers known from the list are applied, the pages of the kept ones are opened (fact sheet:
city, seniority, experience, languages, contract, degree...), then every offer, RSS included, is
judged by the same rules and stored in `offers`, rejected ones with their reasons. The titles set
aside before the detail are listed at the end of the run. One company at a time, nothing written:
`python -u -m scripts.collect_career_site COMPANY URL --db /tmp/try.db --details`.

Career sites registry, in order:

```bash
python -m scripts.build_registry       # search the career sites of new target companies (Serper credits)
python -m scripts.resolve_registry     # propose a job list URL for each company (rules + headless browser)
python -m scripts.verify_registry      # confirm the job lists with the LLM page judge (Gemini calls)
python -m scripts.show_registry        # overview of the registry (read only)
python -m scripts.add_registry_entry "COMPANY" URL   # add a known job list (robots.txt + page judge, no Serper)
```

`python -m evals.check_page_judge` runs the judge on pages verified by hand.

Companies, aliases and the rules (`DEALBREAKERS`, `BONUSES`) are set in `user_config.py`; see the commented example in `user_config.example.py`.
`python -m scripts.rescore [--db PATH] [--dry-run]` applies changed rules to the stored offers, without any LLM call.

## Ideas

### Collection
- Read the job lists of the target companies' career sites (main source)
- Read job offers from the swissdevjobs.ch RSS feed
- Read job alert e-mails from LinkedIn, jobs.ch, jobup.ch, emploi-it.ch and Indeed
- Keep only offers related to IT
- Remove offers already seen

### Scoring
- The LLM states facts (domain, kind of IT job, seniority, languages, contract...), checked in code; it never scores
- The code applies the user's dealbreakers and bonuses to these facts, with the reasons shown
- Matching against local documents (CV, letters, transcripts) with a local LLM only
- Score with the reasons behind it

### Storage
- Local SQLite database, one row per job offer
- Fields: title, company, location, description, source, link, publication date, fetch date, score, status
- Status follows the application: new, interesting, applied, interview, rejected, offer, ignored

### Applications
- Draft adapted CV and cover letter for the best offers
- Human validation before anything is sent

### Security
- Personal documents never sent to a cloud model
- Job offers treated as untrusted input (prompt injection)
- Each agent gets only the tools it needs
- E-mail access limited to a dedicated address

## Roadmap

```
Sources (career sites, RSS, e-mails) → filter → merge duplicates → flags → verify → AI matching → save → notify → human review
```

- **V1 (done):** swissdevjobs RSS, deduplication, rules and score, SQLite storage
- **V1.1 (done):** registry of the target companies' job lists (web search, rules, headless browser, LLM page judge, robots.txt check)
- **V1.2 (in progress, end to end):** read the job lists of the registered career sites (LLM agent for navigation, extraction and checks in code, detail pages), as the main source of offers
- **V1.3:** verify offers from other sources against the career sites (registry lookup, or on-demand search for unknown companies)
- **V1.4:** job alert e-mails (LinkedIn, jobup.ch, jobs.ch, emploi-it.ch, Indeed)
- **V2:** local AI matching against personal documents, with a score and reasons
- **V3:** notification of the best offers
- **V4:** CV and cover letter drafts, with human validation
- **V5:** security hardening (Docker, prompt injection tests)
- **Later:** an agent (search, open page, follow link) for companies whose job list was not found; dedicated readers for common recruiting platforms (Workday, SmartRecruiters, Greenhouse...), faster and more reliable than the headless browser

### Known limitations

- Some swissdevjobs RSS links lead to the job list instead of the offer (offer removed or not available). A search link is shown for each offer as a fallback.
- The RSS feed gives no location.
- Career sites: the agent can skip or repeat a page and its stop reason is not trusted yet (the judge that compares the total announced by the page is still to come). Offers that leave a list are not marked.
- Some career sites block automated access in their robots.txt (e.g. all SuccessFactors sites seen so far); their offers are not read.
- The job list of some companies is not found automatically (empty lists, pages that need a search action, unusual domains). See the design notes for details.