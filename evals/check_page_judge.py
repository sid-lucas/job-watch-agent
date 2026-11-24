"""Check the page judge against pages verified by hand (one LLM call per case)."""
from job_watch.judges.page_judge import judge_page_with_retry
from job_watch.web.browser import render_page

# (company, url, should this page be accepted as the company's job list?)
CASES = [
    ("Richemont", "https://richemont.swiss/jobs/", False,
     "Swiss luxury goods group (Cartier, Jaeger-LeCoultre, Vacheron Constantin, IWC)"),
    ("Lombard Odier", "https://lombardodier.wd3.myworkdayjobs.com/Lombard_Odier_Careers", True),
    ("BCN", "https://www.bcn.ch/la-bcn/carrieres/postes-ouverts", True),
    ("Edmond de Rothschild", "https://evht.fa.ocs.oraclecloud.eu/hcmUI/CandidateExperience/en/sites/CX_7001/jobs", True),
    ("Google", "https://www.google.com/about/careers/applications/jobs/results", True),
    ("Google", "https://careers.google.com/how-we-hire/", False),
    ("Pictet", "https://www.pictet.com/ch/en/careers", False),
    ("KPMG", "https://recruitingapp-2791.umantis.com/Vacancies/8835/DataProtection/2", False),
    ("IBM", "https://careers.ibm.com/en_US/globalform?source=WEB_Search_NA", False),
    ("Microsoft", "https://careers.microsoft.com/", False),
]


def main():
    correct, judged = 0, 0
    for company, url, expected, *context in CASES:
        page = render_page(url)
        if page is None:
            print(f"SKIP  {company:22} page not allowed or failed to load")
            continue
        answer = judge_page_with_retry(company, page, context[0] if context else "")
        if answer is None:
            print(f"SKIP  {company:22} LLM unavailable")
            continue
        judged += 1
        accepted = answer.page_type == "job_list" and answer.owner_matches != "no"
        ok = accepted == expected
        correct += ok
        print(f"{'OK  ' if ok else 'FAIL'}  {company:22} {answer.page_type:13} owner={answer.owner_matches:8} {answer.reason}")
        if answer.jobs_link:
            print(f"      next link: {answer.jobs_link}")
    print(f"\n{correct} / {judged} correct ({len(CASES) - judged} skipped)")


if __name__ == "__main__":
    main()