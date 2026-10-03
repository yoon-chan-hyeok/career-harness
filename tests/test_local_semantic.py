import math

import pytest
from career.semantic import (
    DIMENSIONS,
    PROFILE_ID,
    IndexRequest,
    SearchRequest,
    StoreKind,
    documents,
    index,
    profile_info,
    semantic_search,
)
from career.semantic_models import LocalEvidenceEmbedding
from career.truth import add_evidence, register_source
from pydantic import ValidationError
from sqlalchemy import select


def vector(axis=0):
    return [1.0 if position == axis else 0.0 for position in range(DIMENSIONS)]


def seed(db, user="a", kind="EVIDENCE", status="VERIFIED", path="work"):
    source, _ = register_source(db, user, path, "합성 시험 자료", "MASTER")
    evidence = add_evidence(
        db, user, source.id, "한국어 근거", "매출 자료를 분석해 보고서를 작성했다.", status=status, kind=kind
    )
    return evidence, source


def store(db, evidence_id, user="a", axis=0, kind: StoreKind = "FACT"):
    entry = next(item for item in documents(db, user, kind)["items"] if item["evidence_id"] == evidence_id)
    return index(
        db,
        user,
        IndexRequest.model_validate(
            {
                "profile_id": PROFILE_ID,
                "items": [
                    {
                        "evidence_id": evidence_id,
                        "content_hash": entry["content_hash"],
                        "vector": vector(axis),
                    }
                ],
            }
        ),
    )


def request(kind: StoreKind = "FACT", axis=0, **kwargs):
    return SearchRequest(profile_id=PROFILE_ID, query="자료 분석", vector=vector(axis), kind=kind, **kwargs)


def test_sqlite_vectors_rank_and_prove_private_truth_boundaries(db):
    target, source = seed(db)
    other = add_evidence(db, "a", source.id, "고객", "고객 문의를 응대했다.", status="USER_CONFIRMED")
    unverified = add_evidence(db, "a", source.id, "미확인", "자료 분석", status="UNVERIFIED")
    expression = add_evidence(db, "a", source.id, "표현", "자료 분석", kind="EXPRESSION")
    foreign, _ = seed(db, "b")
    store(db, target.id)
    store(db, other.id, axis=1)
    store(db, expression.id, kind="EXPRESSION")
    store(db, foreign.id, user="b")
    result = semantic_search(db, "a", request())
    assert [item["id"] for item in result["items"]] == [target.id, other.id]
    assert result["indexed_count"] == 2 and result["semantic_used"]
    assert result["items"][0]["semantic_metadata"]["similarity"] == 1.0
    assert result["items"][0]["semantic_metadata"]["basis"] == "SIMILARITY_NOT_DIRECT_FIT_OR_FACT_PROOF"
    assert semantic_search(db, "a", request("EXPRESSION"))["items"][0]["id"] == expression.id
    assert semantic_search(db, "missing-user", request())["items"] == []
    assert unverified.id not in {item["evidence_id"] for item in documents(db, "a")["items"]}
    source.status = "REJECTED"
    db.flush()
    assert semantic_search(db, "a", request())["items"] == []
    assert documents(db, "a", "EXPRESSION")["items"] == []


@pytest.mark.parametrize("change", ["body", "episode", "ownership", "source_hash", "source_status", "status"])
def test_changed_truth_and_source_never_reuses_stale_vector(db, change):
    target, source = seed(db)
    store(db, target.id)
    if change == "body":
        target.body = "정정된 사실"
    elif change == "episode":
        target.data = {"decision_episode": {"decision": "기준을 바꾸었다"}}
    elif change == "ownership":
        target.data = {"ownership": {"implementation": "ASSISTED"}}
    elif change == "source_hash":
        source.content_hash = "corrected"
    elif change == "source_status":
        source.status = "USER_CONFIRMED"
    else:
        target.status = "USER_CONFIRMED"
    db.flush()
    result = semantic_search(db, "a", request())
    assert not result["semantic_used"] and result["items"] == [] and result["stale_count"] == 1
    assert not documents(db, "a")["items"][0]["indexed"]


def test_model_revision_mismatch_and_invalid_vectors_are_rejected(db):
    for bad in [vector()[:383], [math.nan] * DIMENSIONS, [math.inf] * DIMENSIONS, [0.0] * DIMENSIONS]:
        with pytest.raises(ValidationError):
            SearchRequest(profile_id=PROFILE_ID, query="조회", vector=bad)
    with pytest.raises(ValueError, match="모델"):
        semantic_search(db, "a", SearchRequest(profile_id="other-revision", query="조회", vector=vector()))
    profile = profile_info()
    assert profile["dimensions"] == DIMENSIONS and profile["provider_calls"] is False
    assert len(profile["revision"]) == 40 and profile["dtype"] == "q8"


def test_index_rejects_foreign_evidence_and_races_preserve_current_truth(db):
    target, _ = seed(db)
    foreign, _ = seed(db, "b")
    document = documents(db, "a")["items"][0]
    with pytest.raises(ValueError, match="본인 자료"):
        index(
            db,
            "a",
            IndexRequest.model_validate(
                {
                    "profile_id": PROFILE_ID,
                    "items": [
                        {
                            "evidence_id": foreign.id,
                            "content_hash": document["content_hash"],
                            "vector": vector(),
                        }
                    ],
                }
            ),
        )
    target.body = "색인 생성 도중 사용자가 수정한 사실"
    db.flush()
    assert (
        index(
            db,
            "a",
            IndexRequest.model_validate(
                {
                    "profile_id": PROFILE_ID,
                    "items": [
                        {
                            "evidence_id": target.id,
                            "content_hash": document["content_hash"],
                            "vector": vector(),
                        }
                    ],
                }
            ),
        )["stale_skipped"]
        == 1
    )
    assert db.scalar(select(LocalEvidenceEmbedding)) is None
    store(db, target.id)
    assert documents(db, "a")["items"][0]["indexed"]
    store(db, target.id, axis=1)
    assert len(list(db.scalars(select(LocalEvidenceEmbedding)))) == 1
    assert semantic_search(db, "a", request(axis=1))["items"][0]["id"] == target.id


def test_document_cursor_is_bounded_and_does_not_skip_items(db):
    _, source = seed(db)
    for number in range(40):
        add_evidence(db, "a", source.id, f"자료 {number}", "확인된 자료", status="VERIFIED")
    first = documents(db, "a")
    second = documents(db, "a", cursor=first["next_cursor"])
    assert len(first["items"]) == 32 and len(second["items"]) == 9
    assert second["next_cursor"] is None
    assert len({item["evidence_id"] for item in first["items"] + second["items"]}) == 41


def test_wrong_source_owner_and_old_model_vectors_are_excluded(db):
    target, source = seed(db)
    store(db, target.id)
    row = db.scalar(select(LocalEvidenceEmbedding))
    assert row is not None
    row.profile_id = "old-model-profile"
    db.flush()
    assert semantic_search(db, "a", request())["indexed_count"] == 0
    assert not documents(db, "a")["items"][0]["indexed"]
    source.user_id = "b"
    db.flush()
    assert documents(db, "a")["items"] == []


def test_task_metadata_and_blank_queries_preserve_safe_existing_flow(db):
    target, _ = seed(db)
    target.data = {"job_outputs": ["보고서"], "main_skills": ["분석"]}
    store(db, target.id)
    result = semantic_search(db, "a", request(task_context={"actual_outputs": ["보고서"]}, limit=1))
    assert result["items"][0]["retrieval_metadata"]["explicit_output_matches"] == 1
    empty = SearchRequest(profile_id=PROFILE_ID, query="  ", vector=vector(), limit=1)
    assert semantic_search(db, "a", empty)["semantic_used"] is False
    assert semantic_search(db, "a", empty)["items"][0]["id"] == target.id


def test_core_retrieval_fuses_local_semantic_and_lexical_without_losing_task_truth(db):
    from career.retrieval import search

    target, source = seed(db)
    other = add_evidence(db, "a", source.id, "보고서", "핵심 자료", {"job_outputs": ["보고서"]}, "VERIFIED")
    foreign, _ = seed(db, "b")
    store(db, target.id)
    store(db, other.id, axis=1)
    store(db, foreign.id, user="b")
    assert (
        search(db, "a", "다른말로질문", local_vector=vector(), local_profile_id=PROFILE_ID)[0]["id"]
        == target.id
    )
    result = search(
        db,
        "a",
        "자료",
        local_vector=vector(),
        local_profile_id=PROFILE_ID,
        task_context={"actual_outputs": ["보고서"]},
        limit=1,
    )
    assert result[0]["id"] == other.id
    assert result[0]["retrieval_metadata"]["explicit_output_matches"] == 1
    assert foreign.id not in {item["id"] for item in result}
    assert search(db, "a", "", local_vector=vector(), local_profile_id=PROFILE_ID, limit=1)
    with pytest.raises(ValueError, match="모델 정보"):
        search(db, "a", "자료", local_vector=vector())
