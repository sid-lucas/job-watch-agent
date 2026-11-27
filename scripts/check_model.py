"""Check that one model works for every task of the pipeline, before enabling it in config.MODEL_CHAIN.

Three real calls to that model only (no fallback; the triage keeps its one short retry), on
hand-written public data:
1. one triage batch (structured output, a list of items),
2. one criteria call with the criteria of user_config.py (structured output, one field per criterion),
3. one list agent turn (tool calling).
Each step says OK or FAILED, with the time and what was wrong.

    python -u -m scripts.check_model gemini:gemma-4-31b-it
"""
import argparse
import time

from langchain_core.messages import HumanMessage, SystemMessage

from job_watch import config
from job_watch.list_agent.graph import SYSTEM as AGENT_SYSTEM
from job_watch.list_agent.tools import SCHEMAS
from job_watch.llm import structured_llm, tool_llm
from job_watch.offers.ask_criteria import SYSTEM as CRITERIA_SYSTEM, OfferInput, answer_schema, check_offer, user_prompt
from job_watch.offers.criteria import Answer
from job_watch.offers.triage import TriageInput, triage_offers

TITLES = [("Junior SOC Analyst", "Geneva"), ("Accountant (80-100%)", "Lausanne"), ("Cloud Engineer", "Zurich"),
          ("Watchmaker", "Bienne"), ("Data Scientist - LLM", "Geneva")]
AD = """Junior SOC Analyst (80-100%)
Location: Geneva, Switzerland
You monitor security alerts in our Security Operations Center and handle the first steps of incident response.
Requirements: Bachelor in computer science or equivalent. First experience in cybersecurity is a plus.
Languages: French and English, German is an asset. Permanent contract."""
OBSERVATION = """<page>
Observation 1 of https://jobs.example.com/list (page 1)
Junior SOC Analyst - Geneva
Cloud Engineer - Zurich
Elements:
[1] link "Junior SOC Analyst" [blocked: single offer]
[2] button "Next page" [allowed]
[3] link "Apply" [blocked: forbidden_action]
</page>"""


def step(name: str, run) -> bool:
    start = time.monotonic()
    try:
        detail = run()
        print(f"{name}: OK ({time.monotonic() - start:.1f} s) {detail}", flush=True)
        return True
    except Exception as error:       # any provider or schema error: this is what the check reports
        print(f"{name}: FAILED ({time.monotonic() - start:.1f} s) {type(error).__name__}: {str(error)[:300]}",
              flush=True)
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("model", help="provider:model, e.g. gemini:gemma-4-31b-it")
    provider, _, name = parser.parse_args().model.partition(":")
    models = ((provider, name),)

    def triage():
        answers = triage_offers([TriageInput(title=t, location=place, company="Example") for t, place in TITLES],
                                models=models, size=len(TITLES))
        if not all(a.answered for a in answers):
            raise ValueError(f"{sum(not a.answered for a in answers)} of {len(TITLES)} offers without a valid answer")
        return ", ".join(f"{t} -> {a.domain}" for (t, _), a in zip(TITLES, answers))

    def criteria():
        settings = config.SETTINGS
        offer = OfferInput(company="Example Bank", title="Junior SOC Analyst (80-100%)", location="Geneva", ad=AD)
        reply = structured_llm(answer_schema(len(settings.criteria)), models).invoke(
            [("system", CRITERIA_SYSTEM), ("user", user_prompt(settings, offer))])
        raw = [Answer(id=key, answer=value.answer, quote=value.quote) for key, value in reply]
        checked = check_offer(settings, offer, True, raw)
        yes = [a for a in raw if a.answer == "yes"]
        refused = [a for a, c in zip(raw, checked) if a.answer == "yes" and c.answer != "yes"]
        return (f"{len(raw)} answers, {len(yes)} yes, {len(refused)} yes refused by the checks"
                + "".join(f"\n    refused: {a.id} {a.quote[:80]!r}" for a in refused))

    def tools():
        answer = tool_llm(SCHEMAS, models).invoke([SystemMessage(content=AGENT_SYSTEM),
                                                   HumanMessage(content=OBSERVATION)])
        known = {schema.__name__ for schema in SCHEMAS}       # Pydantic classes: the name is the tool name
        if not answer.tool_calls:
            raise ValueError(f"no tool call; text answer: {str(answer.content)[:150]!r}")
        unknown = [c["name"] for c in answer.tool_calls if c["name"] not in known]
        if unknown:
            raise ValueError(f"unknown tools called: {unknown}")
        return ", ".join(f"{c['name']}({c['args']})" for c in answer.tool_calls)

    results = [step("triage (structured output)", triage), step("criteria (structured output)", criteria),
               step("list agent (tool calling)", tools)]
    print(f"\n{provider}:{name}: {'compatible' if all(results) else 'NOT compatible'} "
          f"({sum(results)}/{len(results)} steps OK)")
    raise SystemExit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
