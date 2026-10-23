"""Synthetic guide corpus only; no personal applications or live model calls."""

import json
from copy import deepcopy

import pytest
from career.question_contracts import LengthPolicy, QuestionContract
from career.question_guide_import import (
    GuideRecord,
    GuideRelease,
    catalog,
    import_file,
    load_catalog,
    normalize,
    read_json,
    validate_record,
)
from career.question_guide_search import OfflineVectorScores
from career.question_guide_search import retrieve as raw_retrieve
from career.writing_plans import catalog as legacy_catalog
from career.writing_plans import guide_for
from pydantic import ValidationError


def retrieve(*args, **kwargs):
    return raw_retrieve(*args, enabled=True, **kwargs)


def offline_scores(q, rows, scores):
    preview = retrieve(q, rows)
    return OfflineVectorScores.model_construct(question_revision=q.revision,
                                              corpus_revision=preview["corpus_revision"], scores=scores)


def policy(**changes):
    return {"maximum": 600, "spaces": "INCLUDED", "newlines": "INCLUDED", "title": "INCLUDED", **changes}


def source(guide_id="synthetic:competency", **changes):
    return {"guide_id": guide_id, "version": 1, "source_ref": "https://example.com/synthetic-guide",
            "source_scope": {"company": "합성회사", "role": "개발", "question_id": "Q1"},
            "question": "직무 전문역량과 실제 수행 근거를 설명하세요.", "length": policy(),
            "required_demands": ["전문역량", "실제 수행 근거"], "question_intent": "판단과 수행 근거",
            "allocation": [{"content": label, "approximate_characters": count} for label, count in
                           [("역량 선언", 70), ("문제와 역할", 120), ("기술적 행동", 280), ("성과와 연결", 130)]],
            **changes}


def question(**changes):
    return QuestionContract.model_validate({
        "application_id": "synthetic-application", "question_id": "Q1", "company": "합성회사", "role": "개발",
        "raw_text": "직무 전문역량과 실제 수행 근거를 설명하세요.", "length": policy(), **changes})


def release(record, **changes):
    return GuideRelease.model_validate({"guide_id": record.guide.guide_id, "version": record.guide.version,
                                       "content_hash": record.content_hash, "review_id": "synthetic-review",
                                       "rights": "STRUCTURE_ONLY_APPROVED", "semantic_status": "HUMAN_REVIEWED",
                                       **changes})


def search(q=None, payload=None, **kwargs):
    record = normalize(payload or source())
    return retrieve(q or question(), [record], releases=(release(record),), **kwargs)


def test_original_preserved_provenance_derived_separate_and_json_round_trip():
    payload = source()
    untouched = deepcopy(payload)
    record = normalize(payload)
    assert payload == untouched == record.original_source
    assert record.derived_family == "JOB_COMPETENCY"
    assert "derived_family" not in record.original_source
    assert record.provenance["question"] == "/question"
    assert record.rights_status == "REVIEW_REQUIRED" and not record.source_verified_live
    assert not record.reference_examples_are_applicant_facts
    assert validate_record(GuideRecord.model_validate_json(record.model_dump_json())) == record


def test_import_idempotent_version_immutable_and_new_version_requires_new_release(tmp_path):
    path, folder = tmp_path / "input.json", tmp_path / "catalog"
    payload = source(guide_id="../../must-not-be-a-path")
    path.write_text(json.dumps(payload), encoding="utf-8")
    first = import_file(path, folder)
    assert first.parent == folder
    assert import_file(path, folder) == first
    old = load_catalog(folder)[0]
    payload["question_intent"] = "수정한 의미"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="immutable"):
        import_file(path, folder)
    payload["version"] = 2
    path.write_text(json.dumps(payload), encoding="utf-8")
    import_file(path, folder)
    records = load_catalog(folder)
    assert len(records) == 1 and records[0].guide.version == 2
    assert retrieve(question(), records, releases=(release(old),))["outcome"] == "GUIDE_FALLBACK"
    assert first.exists()  # Historical version retained, not overwritten.


def test_split_versions_and_tampered_saved_records_are_rejected():
    first = normalize(source())
    second = normalize(source(question_intent="different"))
    with pytest.raises(ValueError, match="different content"):
        catalog([first, second])
    assert len(catalog([first, first])) == 1
    changed = first.model_dump(mode="json")
    changed["derived_family"] = "COLLABORATION"
    with pytest.raises(ValueError, match="mismatch"):
        validate_record(GuideRecord.model_validate(changed))


@pytest.mark.parametrize("raw", [b'{"version":1,"version":2}', b'{"x":NaN}', b'{"x":Infinity}', b'[]', b'\xff'])
def test_invalid_json_is_not_silently_normalized(tmp_path, raw):
    path = tmp_path / "invalid.json"
    path.write_bytes(raw)
    with pytest.raises((ValueError, UnicodeDecodeError)):
        read_json(path)


@pytest.mark.parametrize("url", ["file:///tmp/guide", "javascript:alert(1)", "https://u:p@example.com/",
                                "https://example.com/?key=secret", "https://example.com/#fragment"])
def test_source_links_cannot_smuggle_credentials_or_executable_schemes(url):
    with pytest.raises(ValidationError):
        normalize(source(source_ref=url))


@pytest.mark.parametrize("changes", [{"rights_status": "APPROVED"}, {"semantic_reviewed": True},
                                    {"reference_examples_are_applicant_facts": True}, {"version": True},
                                    {"length": policy(maximum=0)}, {"allocation": []},
                                    {"length": policy(unit="BYTES")}])
def test_document_cannot_grant_itself_approval_or_bypass_schema(changes):
    with pytest.raises(ValidationError):
        normalize(source(**changes))


def test_unreviewed_source_never_reaches_candidate_text_or_vector_adapter():
    record = normalize(source(question_intent="PRIVATE_REFERENCE_CANARY"))
    called = []
    result = retrieve(question(), [record], vector_scores=lambda *args: called.append(args) or {})
    assert not called and not result["candidates"]
    assert "PRIVATE_REFERENCE_CANARY" not in json.dumps(result)
    assert result["rejected"][0]["reasons"] == ["RIGHTS_OR_SEMANTIC_REVIEW_REQUIRED"]
    assert result["fallback"]["origin"] == "FALLBACK_TEMPLATE"


def test_exact_uses_original_budgets_but_is_never_claim_or_persona_approval():
    result = search()
    candidate = result["candidates"][0]
    assert result["outcome"] == "EXACT" and candidate["selected_by"] == "SYSTEM_EXACT"
    assert [row["suggested_budget"] for row in candidate["suggested_allocation"]] == [70, 120, 280, 130]
    assert not candidate["approved"] and not result["can_execute"]
    assert candidate["reference_example_mode"] == "NONE"
    assert candidate["candidate_scores"]["rerank"] is None


def test_other_company_and_changed_limit_are_only_advice_with_recomputed_budget():
    original = question(company="현재회사", length=policy(maximum=800))
    result = search(original)
    candidate = result["candidates"][0]
    assert candidate["match_type"] == "ADVISORY_ANALOGY" and candidate["selected_by"] == "NONE"
    assert candidate["source_scope"]["company"] == "합성회사"
    assert candidate["scope_transfer"] and candidate["actual_limit"]["maximum"] == 800
    assert candidate["length_compatible"] is False
    assert sum(row["suggested_budget"] for row in candidate["suggested_allocation"]) == 800
    assert sum(row["approximate_characters"] for row in candidate["source_allocation"]) == 600
    assert original.length.maximum == 800 and original.company == "현재회사"


@pytest.mark.parametrize("text", ["개발 기술을 활용한 협업을 설명하세요.", "개발 중 실패와 극복 경험", "자유 소개"])
def test_shared_technical_keywords_do_not_override_current_question_intent(text):
    result = search(question(raw_text=text))
    assert result["outcome"] == "GUIDE_FALLBACK" and not result["candidates"]
    assert result["rejected"]


def test_failure_is_not_covered_by_a_generic_challenge_guide():
    result = search(question(raw_text="실패를 극복한 도전 경험"),
                    source(question="새로운 목표에 도전한 경험", required_demands=[]))
    assert "REQUIRED_QUESTION_FACET_MISSING" in result["rejected"][0]["reasons"]


def test_explicit_demands_and_negative_topics_override_rank():
    result = search(question(required_demands=["전문역량", "개인 기여 비율"]))
    assert result["rejected"][0]["missing_demands"] == ["개인 기여 비율"]
    result = search(question(excluded_topics=["기술적 행동"]))
    assert result["rejected"][0]["contradictory_demands"] == ["기술적 행동"]


def test_unknown_and_conflicting_counters_do_not_become_verified_exact():
    result = search(question(length={"maximum": 600}))
    assert result["count_policy_confirmation_required"]
    assert result["candidates"][0]["match_type"] == "ADVISORY_ANALOGY"
    assert result["candidates"][0]["length_compatible"] is None
    conflict = search(question(length=policy(spaces="EXCLUDED")))
    assert "COUNT_POLICY_CONFLICT" in conflict["rejected"][0]["reasons"]
    byte = search(question(length=policy(unit="BYTES")))
    assert "LENGTH_UNIT_MISMATCH" in byte["rejected"][0]["reasons"]
    assert byte["fallback"]["budget_status"] == "NEEDS_COUNT_POLICY_CONFIRMATION"
    with pytest.raises(ValidationError):
        LengthPolicy(maximum=600, minimum=601)


def test_empty_corpus_falls_back_and_known_scoped_approval_cannot_transfer():
    assert retrieve(question(), [])["outcome"] == "GUIDE_FALLBACK"
    record = normalize(source())
    result = retrieve(question(company="다른회사"), [record], releases=(release(record, permitted_companies=["합성회사"]),))
    assert result["outcome"] == "GUIDE_FALLBACK"


def test_callback_cannot_execute_or_leak_provider_messages_in_offline_search():
    record = normalize(source())
    secret = normalize(source("unreviewed", question_intent="secret-source-canary"))
    seen = []
    def adapter(query, docs):
        seen.append((query, docs))
        raise RuntimeError("SECRET_PROVIDER_TOKEN")
    result = retrieve(question(company="다른회사"), [record, secret], releases=(release(record),), vector_scores=adapter)
    assert not seen
    assert result["vector_status"] == "UNAVAILABLE_LEXICAL_ONLY"
    assert "SECRET_PROVIDER_TOKEN" not in str(result)
    assert result["outcome"] == "ADVISORY_ANALOGY"


@pytest.mark.parametrize("scores", [{"foreign-evidence-id": .99}, {"synthetic:competency": float("nan")},
                                   {"synthetic:competency": True}])
def test_bad_vector_results_fail_closed_to_lexical(scores):
    q, record = question(company="다른회사"), normalize(source())
    result = search(q, vector_scores=offline_scores(q, [record], scores))
    assert result["vector_status"] == "UNAVAILABLE_LEXICAL_ONLY"
    assert result["candidates"][0]["candidate_scores"]["vector"] is None


def test_hybrid_candidates_stable_bounded_and_revision_changes_with_source_or_review():
    rows = [normalize(source(str(i))) for i in range(5)]
    reviews = tuple(release(row, review_id="review-" + row.guide.guide_id) for row in rows)
    q = question(company="another")
    index = offline_scores(q, rows, {row.guide.guide_id: .5 for row in rows})
    result = retrieve(q, rows, releases=reviews, vector_scores=index)
    assert len(result["candidates"]) == 3 and result["omitted_candidate_count"] == 2
    assert result == retrieve(q, list(reversed(rows)), releases=tuple(reversed(reviews)),
                              vector_scores=index)
    assert result["retrieval_run_id"] != retrieve(q, rows, releases=reviews[:-1])["retrieval_run_id"]
    with pytest.raises(ValueError):
        retrieve(q, rows, max_candidates=4)


def test_legacy_mini_kit_preserved_no_full_example_in_new_retrieval():
    legacy = legacy_catalog()
    assert len(legacy) == 1  # This repository has one source, not an invented 877-guide corpus.
    record = normalize(legacy[0], legacy=True)
    assert record.guide.length.needs_confirmation
    q = question(company=record.guide.source_scope.company, role=record.guide.source_scope.role,
                 raw_text=record.guide.question, length={"maximum": 600})
    result = retrieve(q, [record])
    assert result["outcome"] == "GUIDE_FALLBACK"  # No publication/semantic release was supplied.
    assert "1만 2천" not in str(result) and "3.8%" not in str(result)
    old = guide_for(q.company, q.role, {"text": q.raw_text, "limit": q.length.maximum})
    assert old["origin"] == "ARCHIVED_REFERENCE"
    assert [row["approximate_characters"] for row in old["allocation"]] == [70, 120, 280, 130]
    assert old["reference_example"]["total_characters"] == 592


def test_local_cli_import_inventory_search_without_database(tmp_path, monkeypatch, capsys):
    from career.question_guide_cli import main
    source_path, question_path = tmp_path / "guide.json", tmp_path / "question.json"
    folder = tmp_path / "catalog"
    source_path.write_text(json.dumps(source()), encoding="utf-8")
    question_path.write_text(question().model_dump_json(), encoding="utf-8")
    for args in [["import", str(source_path)], ["inventory"], ["search", str(question_path)]]:
        monkeypatch.setattr("sys.argv", ["guide-cli", *args, "--catalog", str(folder)])
        main()
        output = json.loads(capsys.readouterr().out)
        assert "original_source" not in output
    assert output["outcome"] == "GUIDE_FALLBACK"
    assert len(list(folder.glob("*.json"))) == 1
    ledger = tmp_path / "release.json"
    ledger.write_text(json.dumps({"reviews": [release(load_catalog(folder)[0]).model_dump(mode="json")]}),
                      encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["guide-cli", "search", str(question_path), "--catalog", str(folder),
                                    "--releases", str(ledger), "--enable-guide-preview"])
    main()
    assert json.loads(capsys.readouterr().out)["outcome"] == "EXACT"


def test_import_input_size_limit(tmp_path):
    path = tmp_path / "large.json"
    path.write_bytes(b" " * 2_000_001)
    with pytest.raises(ValueError, match="budget"):
        read_json(path)
