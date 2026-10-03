import json

from career.models import Evidence, Fact, Source
from career.truth import add_fact, canonical, import_corpus, register_source
from sqlalchemy import func, select


def test_profile_correction_wins_and_is_scoped(db):
    old, _ = register_source(db, "a", "master", "old", "MASTER")
    fact = add_fact(db, "a", old.id, "profile", "graduation", {"text": "expected"})
    correction, _ = register_source(db, "a", "correction", "graduated", "USER_CORRECTION")
    add_fact(db, "a", correction.id, "profile", "graduation", {"text": "graduated"})
    assert fact.status == "SUPERSEDED"
    assert canonical(db, "a")["profile:graduation"]["value"]["text"] == "graduated"
    assert canonical(db, "b") == {}


def test_raw_metric_beats_memory_and_equal_authority_conflicts(db):
    raw, _ = register_source(db, "a", "raw", "80%", "RAW_RESULT")
    memory, _ = register_source(db, "a", "memory", "90%", "MEMORY")
    add_fact(db, "a", raw.id, "metric", "accuracy", {"value": 80})
    remembered = add_fact(db, "a", memory.id, "metric", "accuracy", {"value": 90})
    assert remembered.status == "SUPERSEDED"
    other, _ = register_source(db, "a", "other", "85%", "RAW_RESULT")
    add_fact(db, "a", other.id, "metric", "accuracy", {"value": 85})
    assert canonical(db, "a") == {}


def test_import_empty_recursive_idempotent_expression_separation(db, tmp_path):
    assert import_corpus(db, "a", tmp_path)["sources_added"] == 0
    folder = tmp_path / "final_applications" / "old"
    folder.mkdir(parents=True)
    (folder / "draft.md").write_text("졸업 예정, 정확도 99%", "utf-8")
    assert import_corpus(db, "a", tmp_path)["sources_added"] == 1
    assert import_corpus(db, "a", tmp_path)["skipped"] == 1
    assert db.scalar(select(func.count()).select_from(Source)) == 1
    assert db.scalar(select(func.count()).select_from(Fact)) == 0
    assert db.scalar(select(Evidence)).kind == "EXPRESSION"


def test_malformed_source_rolls_back_and_can_retry(db, tmp_path):
    file = tmp_path / "bad.json"
    file.write_text("{", "utf-8")
    assert import_corpus(db, "a", tmp_path)["errors"]
    assert db.scalar(select(func.count()).select_from(Source)) == 0
    file.write_text(json.dumps({"type": "APPLICATION", "status": "materials_prepared"}), "utf-8")
    assert import_corpus(db, "a", tmp_path)["sources_added"] == 1
