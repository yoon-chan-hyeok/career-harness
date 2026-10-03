from career.decisions import Decision, JevDecisionProvider, shadow_decision
from career.evaluation import benchmark, production_metrics
from career.models import PromptRun
from career.providers import FakeLLMProvider
from sqlalchemy import select


class Primary:
    def choose(self, task_id: str, state: dict, options: list[str]):
        return Decision(choice="yes", confidence="HIGH", rationale="fixture")

    def binary(self, task_id: str, state: dict):
        return True

    def score(self, task_id: str, state: dict, scale: list[str]):
        return "HIGH"


def test_shadow_failure_cannot_change_primary(db):
    result = shadow_decision(db, "a", Primary(), JevDecisionProvider(), "direct_answer", {}, ["yes", "no"])
    assert result.choice == "yes"
    db.flush()
    assert db.scalar(select(PromptRun)).data["error_type"] == "ProviderUnavailable"


def test_no_metrics_fabricated_without_production_data(db):
    assert production_metrics(db, "a")["acceptance_rate"] is None


def test_baselines_run_with_distinct_contexts():
    contexts = []

    class Spy(FakeLLMProvider):
        def structured(self, prompt_id, context, schema):
            if prompt_id == "benchmark_writer":
                contexts.append(context)
            return super().structured(prompt_id, context, schema)

    provider = Spy(
        {
            "benchmark_writer": {"text": "검증했습니다.", "claims": []},
            "benchmark_review": {"issues": [], "followups": []},
        }
    )
    case = {
        "jd": "직무",
        "question": "문항",
        "strategy": {"positioning": "검증"},
        "evidence": [{"body": "검증했습니다.", "source_id": "s", "status": "VERIFIED"}],
    }
    result = benchmark(provider, case)
    assert len(result["results"]) == 4
    assert "selected_evidence" not in contexts[0]
    assert "strategy" not in contexts[1]
    assert "strategy" in contexts[2]
