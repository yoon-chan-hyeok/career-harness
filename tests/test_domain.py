import pytest
from career.domain import save_entity
from career.truth import add_evidence, register_source


def test_ownership_cannot_be_upgraded_silently(db):
    source, _ = register_source(db, "a", "s", "내용", "MASTER")
    e = add_evidence(db, "a", source.id, "project", "내용")
    data = {"source_id": source.id, "evidence_id": e.id, "implementation": "USER"}
    with pytest.raises(ValueError, match="확인"):
        save_entity(db, "a", "Ownership", data)
    save_entity(db, "a", "Ownership", data, explicit_confirmation=True)
    assert e.data["ownership"]["implementation"] == "USER"


def test_metric_requires_scope_and_provenance(db):
    source, _ = register_source(db, "a", "s", "80%", "RAW_RESULT")
    e = add_evidence(db, "a", source.id, "project", "80%")
    with pytest.raises(ValueError):
        save_entity(
            db,
            "a",
            "Metric",
            {"source_id": source.id, "evidence_id": e.id, "name": "accuracy", "value": "80"},
        )
    payload = {
        "source_id": source.id,
        "evidence_id": e.id,
        "name": "accuracy",
        "value": "80",
        "unit": "%",
        "dataset": "test",
        "subset": "heldout",
        "experiment_version": "v2",
        "baseline": None,
        "denominator": "100",
        "valid_for_claims": ["heldout accuracy"],
        "invalid_for_claims": ["production performance"],
    }
    record = save_entity(db, "a", "Metric", payload)
    assert record.data["subset"] == "heldout"
    with pytest.raises(LookupError):
        save_entity(db, "b", "Metric", payload)


def test_writing_rule_promotion_requires_confirmation(db):
    source, _ = register_source(db, "a", "s", "rule", "MASTER")
    data = {
        "source_id": source.id,
        "scope_type": "USER",
        "scope_value": "a",
        "rule_type": "style",
        "rule": "keep simple",
        "status": "CANONICAL",
    }
    with pytest.raises(ValueError):
        save_entity(db, "a", "WritingRule", data)
