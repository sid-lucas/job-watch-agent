"""Builders shared by tests (no LLM, no browser)."""
from job_watch.offers import ask_criteria
from job_watch.offers.ask_criteria import answer_schema
from job_watch.offers.criteria import Settings, load_settings


def criteria_settings(criteria: list[dict], code_criteria: list[dict] | None = None,
                      kept_domains: list[str] | None = None) -> Settings:
    return load_settings("Test profile.", criteria, code_criteria or [], kept_domains or ["Technology/IT", "Other"])


class FakeCriteriaModel:
    """Answers the criteria with `answer(prompt)` -> {"c1": ("yes", "quote")}; the others are unknown.
    Records the user prompts."""

    def __init__(self, settings: Settings, answer):
        self.settings, self.answer, self.prompts = settings, answer, []

    def invoke(self, messages):
        prompt = messages[1][1]
        self.prompts.append(prompt)
        fields = {f"c{i + 1}": {"answer": "unknown", "quote": ""} for i in range(len(self.settings.criteria))}
        fields.update({k: {"answer": a, "quote": q} for k, (a, q) in self.answer(prompt).items()})
        return answer_schema(len(self.settings.criteria))(**fields)


def fake_criteria(monkeypatch, settings: Settings, answer) -> FakeCriteriaModel:
    """config.SETTINGS replaced by `settings`, and the criteria answered by a fake model."""
    from job_watch import config
    monkeypatch.setattr(config, "SETTINGS", settings)
    model = FakeCriteriaModel(settings, answer)
    monkeypatch.setattr(ask_criteria, "structured_llm", lambda schema: model)
    return model
