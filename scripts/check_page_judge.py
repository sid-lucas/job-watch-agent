"""Check the page judge against pages verified by hand (7 LLM calls)."""
from job_watch.browser import render_page
from job_watch.page_judge import judge_page

# (company, url, is the page a job list?)
CASES = [
    ("Lombard Odier", "https://lombardodier.wd3.myworkdayjobs.com/Lombard_Odier_Careers", True),
    ("BCN", "https://www.bcn.ch/la-bcn/carrieres/postes-ouverts", True),
    ("Google", "https://www.google.com/about/careers/applications/jobs/results?hl=en_US", True),
    ("Google", "https://careers.google.com/how-we-hire/", False),
    ("Pictet", "https://www.pictet.com/ch/en/careers", False),
    ("KPMG", "https://recruitingapp-2791.umantis.com/Vacancies/8835/DataProtection/2", False),
    ("IBM", "https://careers.ibm.com/en_US/globalform?source=WEB_Search_NA", False),
    ("Microsoft", "https://careers.microsoft.com/", False),
]


def main():
    correct = 0
    for company, url, expected in CASES:
        page = render_page(url)
        if page is None:
            print(f"SKIP  {company:14} page not allowed or failed to load")
            continue
        answer = judge_page(company, page)
        ok = (answer.page_type == "job_list") == expected
        correct += ok
        print(f"{'OK  ' if ok else 'FAIL'}  {company:14} {answer.page_type:13} {answer.reason}")
        if answer.jobs_link:
            print(f"      next link: {answer.jobs_link}")
    print(f"\n{correct} / {len(CASES)} correct")


if __name__ == "__main__":
    main()