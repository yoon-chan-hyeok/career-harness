import json
from pathlib import Path

import pytest
from career.models import Artifact
from career.telemetry import export_events, feedback
from career.validation import hard_qa


@pytest.mark.parametrize(
    "text,updates,code",
    [
        ("정확도 99%", {}, "UNSUPPORTED_METRIC"),
        ("혼자 개발", {}, "OWNERSHIP"),
        ("전체 시스템 개발", {}, "CLAIM_BOUNDARY"),
        ("검증", {"status": "SUPERSEDED"}, "STALE_SOURCE"),
        ("검증", {"source_id": ""}, "MISSING_SOURCE"),
    ],
)
def test_hard_violations(text, updates, code):
    item = {
        "body": "검증 정확도 80%",
        "status": "VERIFIED",
        "source_id": "source",
        "data": {"forbidden_claims": ["전체 시스템 개발"], "ownership": {"implementation": "TEAM"}},
        **updates,
    }
    assert code in [i["code"] for i in hard_qa(text, [item])]


def test_feedback_roundtrip_and_isolation(db):
    a = Artifact(user_id="alice", workspace_id="w", kind="Draft", data={"text": "hello"})
    db.add(a)
    db.flush()
    feedback(db, "alice", a, "EDIT", "hello", "hello world")
    db.commit()
    assert export_events(db, "alice")[0]["after"] == "hello world"
    assert export_events(db, "bob") == []


def test_historical_case_schema():
    cases = [
        json.loads(line) for line in Path("evals/historical_cases.jsonl").read_text("utf-8").splitlines()
    ]
    assert len(cases) == 8
    assert all({"id", "input", "bad_behavior", "expected_behavior", "target"} <= c.keys() for c in cases)
