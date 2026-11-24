# job-watch

Job monitoring system for IT positions in Switzerland.
It collects job offers from authorized sources, filters and scores them against a candidate profile, and prepares application drafts for human review.

## Usage

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python main.py
```

Each run fetches the RSS feed, filters and scores the offers, stores them in `data/offers.db`, and lists the best new offers since the last run.
Rules (keywords, companies, reject and score rules) are set in `config.py`.

## Ideas

### Collection
- Read job offers from the swissdevjobs.ch RSS feed
- Read job alert e-mails from jobs.ch, jobup.ch and emploi-it.ch
- Keep only offers related to IT
- Remove offers already seen

### Scoring
- Red flags that remove an offer (e.g. outside Switzerland, fluent German required)
- Green flags that raise the score (e.g. junior/graduate, Geneva or Zurich, large company)
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
Sources → filter → merge duplicates → flags → verify (top offers) → AI matching → save → notify → human review
```

- **V1:** swissdevjobs RSS, keyword filter, deduplication, red/green flags, SQLite storage
- **V1.1:** job alert e-mails (LinkedIn, jobup.ch, jobs.ch, emploi-it.ch, Indeed)
- **V1.2:** check that the best offers still exist on the company's career site, and get the full description and official link
- **V2:** local AI matching against personal documents, with a score and reasons
- **V3:** notification of the best offers
- **V4:** CV and cover letter drafts, with human validation
- **V5:** security hardening (Docker, prompt injection tests)

### Known limitations

- Some swissdevjobs RSS links lead to the job list instead of the offer (offer removed or not available). A search link is shown for each offer as a fallback.
- The RSS feed gives no location.