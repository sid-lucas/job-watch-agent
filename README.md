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

Personal settings (keywords, target companies, scoring rules):

```bash
cp user_config.example.py user_config.py
```

Then edit `user_config.py`. This file is not committed: each user keeps their own.

API keys go in a `.env` file at the project root (not committed):

```
SERPER_API_KEY=...
GEMINI_API_KEY=...
```

## Project structure

```
job_watch/              application code (graph, nodes, storage, registry, web access, browser, LLM judge)
scripts/                exploration and maintenance scripts
docs/                   design notes
data/                   local database and registry (not committed)
main.py                 entry point
user_config.example.py  template for personal settings
```

Run everything from the project root: `python main.py`, and `python -m scripts.<name>` for scripts.

How things work and why: see [docs/design-notes.md](docs/design-notes.md).

## Usage

```bash
python main.py                       # fetch, filter, score and store offers, list the best new ones
python -m scripts.build_registry     # search the career sites of new target companies (Serper credits)
python -m scripts.resolve_registry   # choose the job list URL of each company
```

Rules (keywords, companies, aliases, reject and score rules) are set in `user_config.py`.

## Ideas

### Collection
- Read the job lists of the target companies' career sites (main source)
- Read job offers from the swissdevjobs.ch RSS feed
- Read job alert e-mails from LinkedIn, jobs.ch, jobup.ch, emploi-it.ch and Indeed
- Keep only offers related to IT
- Remove offers already seen

### Scoring
- Red flags that remove an offer (e.g. senior/management title, ad written in German)
- Green flags that raise the score (e.g. junior/graduate, Geneva or Zurich, top company)
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

- **V1:** swissdevjobs RSS, keyword filter, deduplication, red/green flags, SQLite storage
- **V1.1:** registry of the target companies' career sites (job list URL, recruiting platform, robots.txt check)
- **V1.2:** read the job lists of the registered career sites (headless browser + LLM extraction), as the main source of offers
- **V1.3:** verify offers from other sources against the career sites (registry lookup, or on-demand search for unknown companies)
- **V1.4:** job alert e-mails (LinkedIn, jobup.ch, jobs.ch, emploi-it.ch, Indeed)
- **V2:** local AI matching against personal documents, with a score and reasons
- **V3:** notification of the best offers
- **V4:** CV and cover letter drafts, with human validation
- **V5:** security hardening (Docker, prompt injection tests)
- **Later:** dedicated readers for common recruiting platforms (Workday, SmartRecruiters, Greenhouse...), faster and more reliable than the headless browser

### Known limitations

- Some swissdevjobs RSS links lead to the job list instead of the offer (offer removed or not available). A search link is shown for each offer as a fallback.
- The RSS feed gives no location.
- Some career sites block automated access in their robots.txt; their offers are not read.