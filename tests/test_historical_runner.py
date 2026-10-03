import json
from pathlib import Path

from career.evaluation import historical_smoke, reviewer_metrics


def test_existing_historical_cases_executed_against_injected_guard():
    class FixtureGuard:
        def structured(self, prompt_id, context, schema):
            return schema.model_validate(
                {"rejected": context["candidate"] != context["criterion"], "reason": "Fixture only"}
            )

    cases = [
        json.loads(line) for line in Path("evals/historical_cases.jsonl").read_text("utf-8").splitlines()
    ]
    result = historical_smoke(FixtureGuard(), cases)
    assert result["passed"] == 8
    assert result["label"] == "MODEL_JUDGED_SMOKE_NOT_HUMAN_VALIDATION"


def test_reviewer_precision_only_uses_observed_labels():
    assert reviewer_metrics([])["issue_precision"] is None
    result = reviewer_metrics([{"valid": True, "accepted": True}, {"valid": False, "accepted": False}])
    assert result["issue_precision"] == 0.5
