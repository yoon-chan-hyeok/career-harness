import pytest
from career.retrieval import compile_context, search, style_projection
from career.truth import add_evidence, register_source


def test_retrieval_respects_store_user_and_verification(db):
    source, _ = register_source(db, "a", "source", "x", "MASTER")
    add_evidence(db, "a", source.id, "RAG", "failure detection", status="VERIFIED")
    add_evidence(db, "a", source.id, "RAG", "unverified", status="UNVERIFIED")
    add_evidence(db, "a", source.id, "RAG", "old expression", status="VERIFIED", kind="EXPRESSION")
    assert len(search(db, "a", "RAG")) == 1
    assert search(db, "b", "RAG") == []
    assert search(db, "a", "RAG", "EXPRESSION")[0]["body"] == "old expression"


def test_context_boundaries():
    assert set(compile_context("recruiter", evidence=[{"secret": "private"}])) == {"jd", "question", "draft"}
    with pytest.raises(ValueError):
        compile_context("writer", brief={"evidence_ids": ["missing"]}, evidence=[])
    assert "99%" not in str(style_projection({"body": "Old company 99%"}))


def test_multiple_job_outputs_are_or_matched_with_korean_partial_and_bounded_blank(db):
    source, _ = register_source(db, "a", "outputs", "합성 근거", "MASTER")
    report = add_evidence(db, "a", source.id, "보고서 작성", "분석보고서를 작성했다", status="VERIFIED")
    dashboard = add_evidence(db, "a", source.id, "대시보드", "현황을 시각화했다", status="USER_CONFIRMED")
    episode = add_evidence(
        db,
        "a",
        source.id,
        "판단",
        "기준",
        {"decision_episode": {"decision": "데이터정제 기준을 정했다"}},
        "VERIFIED",
    )
    assert {item["id"] for item in search(db, "a", "보고서 대시보드")} == {report.id, dashboard.id}
    assert search(db, "a", "분석보고")[0]["id"] == report.id
    assert search(db, "a", "데이터정제")[0]["id"] == episode.id
    assert len(search(db, "a", "", limit=1)) == 1
    assert search(db, "a", "없는단어") == []
    source.status = "REJECTED"
    db.flush()
    assert search(db, "a", "보고서 대시보드") == []
