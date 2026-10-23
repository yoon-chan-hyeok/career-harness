"""Integrated I01 boundary regression: synthetic data and the existing public fixture only."""

import json
from copy import deepcopy
from typing import Any, cast

import pytest
from career.models import Evidence, Source
from career.question_contracts import QuestionContract
from career.question_guide_cli import main
from career.question_guide_import import (
    catalog,
    import_file,
    load_catalog,
    normalize,
    source_manifest,
)
from career.question_guide_search import OfflineVectorScores, retrieve
from career.writing_plans import TEMPLATES, guide_for
from career.writing_plans import catalog as legacy_catalog
from test_question_guide_retrieval import question, release, source


@pytest.mark.parametrize("injection", [
    {"user_id": "private-marker"}, {"namespace": "USER_EVIDENCE"},
    {"private_evidence": "private-marker"}, {"fact_ids": ["private-marker"]},
])
@pytest.mark.parametrize("location", ["root", "nested", "list"])
def test_personal_truth_rejected_in_legacy_at_every_depth(injection, location):
    payload = deepcopy(legacy_catalog()[0])
    if location == "root":
        payload.update(injection)
    else:
        payload["guide"]["metadata"] = injection if location == "nested" else [injection]
    with pytest.raises(ValueError) as error:
        normalize(payload, legacy=True)
    assert "private-marker" not in str(error.value)


@pytest.mark.parametrize("personal", [Source(user_id="private-marker"), Evidence(user_id="private-marker"),
                                      {"namespace": "USER_EVIDENCE", "user_id": "private-marker"}])
def test_actual_personal_models_cannot_enter_global_catalog(personal):
    with pytest.raises(ValueError, match="personal Source/Evidence") as error:
        catalog([personal])
    assert "private-marker" not in str(error.value)


def legacy_question(record, **changes):
    return QuestionContract.model_validate({
        "application_id": "synthetic", "question_id": "Q1", "company": record.guide.source_scope.company,
        "role": record.guide.source_scope.role, "raw_text": record.guide.question,
        "length": {"maximum": 600}, **changes})


def test_legacy_exact_preserves_counts_and_original_hash_without_approving_unknown_policy(tmp_path):
    payload = legacy_catalog()[0]
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    target = import_file(path, tmp_path / "catalog", legacy=True)
    before = target.read_bytes()
    assert import_file(path, tmp_path / "catalog", legacy=True) == target
    assert target.read_bytes() == before
    record = load_catalog(tmp_path / "catalog")[0]
    assert record.content_hash == "09f69cbb475d07ed85296e75e8180a61c59e8dc9795f308ddc1a44b160d63e2d"
    q = legacy_question(record)
    result = retrieve(q, [record], releases=(release(record),), enabled=True)
    candidate = result["candidates"][0]
    assert candidate["match_type"] == "EXACT" and candidate["match_policy"] == "LEGACY_EXACT"
    assert [part["suggested_budget"] for part in candidate["suggested_allocation"]] == [70, 120, 280, 130]
    assert result["count_policy_confirmation_required"] and candidate["length_compatible"] is None
    assert candidate["status"] == "CANDIDATE_NOT_APPROVED" and not candidate["approved"]
    assert candidate["source_manifest"]["rights_status"] == "RIGHTS_PENDING"
    assert "reference_example" not in candidate and "original_source" not in candidate
    assert guide_for(q.company, q.role, {"text": q.raw_text, "limit": 600})["origin"] == "ARCHIVED_REFERENCE"


def test_exact_and_disabled_paths_do_not_execute_scoring_or_callbacks(monkeypatch):
    record = normalize(source())

    def forbidden(*args, **kwargs):
        raise AssertionError("scoring/provider callback executed")

    monkeypatch.setattr("career.question_guide_search.lexical_scores", forbidden)
    exact = retrieve(question(), [record], releases=(release(record),), enabled=True, vector_scores=cast(Any, forbidden))
    assert exact["retrieval_mode"] == "EXACT_ONLY" and exact["vector_status"] == "NOT_NEEDED_EXACT"
    assert exact["candidates"][0]["match_policy"] == "STRICT_EXACT"
    disabled = retrieve(question(), [cast(Any, object())], vector_scores=cast(Any, forbidden))
    assert disabled["fallback_reason"] == "FEATURE_DISABLED" and not disabled["candidates"]
    assert not disabled["semantic_search_executed"] and not disabled["can_execute"]


@pytest.mark.parametrize("raw_text", [
    "협업 경험은 제외하고 개인의 기술 역량을 설명하세요.",
    "협업이 아니라 개인의 기술 역량을 설명하세요.",
    "협업 없이 혼자 해결한 기술 문제를 설명하세요.",
])
def test_negative_requirements_are_not_positive_collaboration_advice(raw_text):
    record = normalize(source(question="협업을 통해 공동 목표를 달성한 경험을 설명하세요.",
                              required_demands=["협업"], question_intent="협업 행동과 역할"))
    result = retrieve(question(raw_text=raw_text), [record], releases=(release(record),), enabled=True)
    assert result["outcome"] == "GUIDE_FALLBACK" and result["fallback"]["family"] == "OTHER"
    assert "NEGATIVE_REQUIREMENT_REQUIRES_REVIEW" in result["rejected"][0]["reasons"]


@pytest.mark.parametrize("rights", ["PUBLIC_APPROVED", "PRIVATE_REFERENCE", "RIGHTS_PENDING", "RESTRICTED"])
def test_publication_permission_is_separate_from_structural_execution(rights):
    record = normalize(source())
    review = release(record, source_rights=rights)
    manifest = source_manifest(record, review)
    assert manifest.rights_status == rights and manifest.namespace == "QUESTION_GUIDES"
    assert not manifest.full_text_publication_enabled and manifest.public_example_mode == "NONE"
    result = retrieve(question(), [record], releases=(review,), enabled=True)
    if rights == "RESTRICTED":
        assert manifest.execution_permission == "DENIED" and not result["candidates"]
    else:
        assert manifest.execution_permission == "STRUCTURE_REFERENCE_ALLOWED"
        candidate = result["candidates"][0]
        assert not candidate["approved"] and candidate["public_example_mode"] == "NONE"
    assert source_manifest(record).execution_permission == "REVIEW_REQUIRED"
    with pytest.raises(ValueError, match="source version"):
        source_manifest(record, release(record, content_hash="0" * 64))


@pytest.mark.parametrize("reverse", [False, True])
def test_conflicting_release_ledger_fails_closed_in_either_order(reverse):
    record = normalize(source())
    reviews = (release(record, source_rights="PUBLIC_APPROVED"),
               release(record, source_rights="RESTRICTED", review_id="revocation"))
    with pytest.raises(ValueError, match="ambiguous duplicate"):
        retrieve(question(), [record], releases=reviews[::-1] if reverse else reviews, enabled=True)


@pytest.mark.parametrize("field,value", [
    ("namespace", "USER_EVIDENCE"), ("question_revision", "stale-question"),
    ("corpus_revision", "stale-corpus"), ("scores", {"personal-evidence": 1.0}),
])
def test_stale_or_foreign_precomputed_index_falls_back_to_lexical(field, value):
    q, record = question(company="another"), normalize(source())
    reviews = (release(record),)
    initial = retrieve(q, [record], releases=reviews, enabled=True)
    values = {"namespace": "QUESTION_GUIDES", "question_revision": q.revision,
              "corpus_revision": initial["corpus_revision"], "scores": {record.guide.guide_id: .5}, field: value}
    index = OfflineVectorScores.model_construct(**values)
    result = retrieve(q, [record], releases=reviews, enabled=True, vector_scores=index)
    assert result["vector_status"] == "UNAVAILABLE_LEXICAL_ONLY"
    assert result["retrieval_mode"] == "LEXICAL_ONLY" and not result["semantic_search_executed"]
    assert result["outcome"] == "ADVISORY_ANALOGY"


def test_candidate_identity_changes_with_review_or_question():
    q, record = question(), normalize(source())
    def run(current, review):
        return retrieve(current, [record], releases=(review,), enabled=True)["request_key"]
    initial = run(q, release(record))
    assert initial != run(q, release(record, review_id="new-review"))
    assert initial != run(question(version=2), release(record))


@pytest.mark.parametrize("text,expected", [
    ("직무 역량", "JOB_COMPETENCY"), ("지원 동기", "MOTIVATION"), ("협업", "COLLABORATION"),
    ("도전", "CHALLENGE"), ("장단점", "STRENGTH_WEAKNESS"), ("가치관", "VALUES"), ("자유", "OTHER"),
])
def test_seven_fallback_families_without_guides(text, expected):
    result = retrieve(question(raw_text=text), [], enabled=True)
    assert len(TEMPLATES) == 7 and result["fallback"]["family"] == expected
    assert result["outcome"] == "GUIDE_FALLBACK"
    assert sum(part["suggested_budget"] for part in result["fallback"]["allocation"]) == 600


@pytest.mark.parametrize("flag,env,enabled", [(False, "0", False), (False, "true", False),
                                              (False, "1", True), (True, "0", True)])
def test_cli_opt_in_is_explicit(tmp_path, monkeypatch, capsys, flag, env, enabled):
    input_path, qpath, ledger = (tmp_path / name for name in ("guide.json", "question.json", "releases.json"))
    input_path.write_text(json.dumps(source()), encoding="utf-8")
    qpath.write_text(question().model_dump_json(), encoding="utf-8")
    folder = tmp_path / "catalog"
    import_file(input_path, folder)
    ledger.write_text(json.dumps({"reviews": [release(load_catalog(folder)[0]).model_dump(mode="json")]}),
                      encoding="utf-8")
    args = ["guide-cli", "search", str(qpath), "--catalog", str(folder), "--releases", str(ledger)]
    monkeypatch.setattr("sys.argv", args + (["--enable-guide-preview"] if flag else []))
    monkeypatch.setenv("QUESTION_GUIDE_RAG_ENABLED", env)
    main()
    result = json.loads(capsys.readouterr().out)
    assert result["feature_enabled"] is enabled
    assert result["outcome"] == ("EXACT" if enabled else "GUIDE_FALLBACK")



@pytest.mark.parametrize("changes,budget", [
    ({"company": "다른회사"}, 600),
    ({"role": "다른직무"}, 600),
    ({"length": {"maximum": 800}}, 800),
])
def test_legacy_exact_requires_company_role_and_current_limit_independently(changes, budget):
    record = normalize(legacy_catalog()[0], legacy=True)
    q = legacy_question(record, **changes)
    result = retrieve(q, [record], releases=(release(record),), enabled=True)
    candidate = result["candidates"][0]
    assert candidate["match_type"] == "ADVISORY_ANALOGY"
    assert sum(part["suggested_budget"] for part in candidate["suggested_allocation"]) == budget
    assert [part["approximate_characters"] for part in candidate["source_allocation"]] == [70, 120, 280, 130]
    assert guide_for(q.company, q.role, {"text": q.raw_text, "limit": budget})["origin"] != "ARCHIVED_REFERENCE"
