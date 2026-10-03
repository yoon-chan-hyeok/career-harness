from career.retrieval import search
from career.truth import add_evidence, register_source


def test_task_metadata_prioritizes_actual_work_without_claiming_fit_or_leaking(db):
    source, _ = register_source(db, "a", "tasks", "report", "RAW_RESULT")
    add_evidence(db, "a", source.id, "report tool", "report tool", status="VERIFIED")
    target = add_evidence(
        db,
        "a",
        source.id,
        "report experiment",
        "report analysis",
        {
            "job_outputs": ["report"],
            "main_skills": ["analysis"],
            "decision_episode": {"decision": "changed criteria"},
        },
        "VERIFIED",
    )
    result = search(
        db, "a", "report", limit=1, task_context={"actual_outputs": ["report"], "main_skills": ["analysis"]}
    )
    assert result[0]["id"] == target.id
    assert result[0]["retrieval_metadata"]["basis"] == "RETRIEVAL_PRIORITY_NOT_DIRECT_FIT_OR_FACT_PROOF"
    assert search(db, "b", "report", task_context={"actual_outputs": ["report"]}) == []
    assert search(db, "a", "changed criteria")[0]["id"] == target.id


def test_upload_unknown_ownership_remains_unknown_during_task_ranking(db):
    source, _ = register_source(db, "a", "uploaded", "합성 근거", "MASTER")
    item = add_evidence(
        db, "a", source.id, "보고서", "보고서를 작성했다", {"ownership": "UNKNOWN"}, "USER_CONFIRMED"
    )
    result = search(db, "a", "보고서", task_context={"actual_outputs": ["보고서"]})
    assert result[0]["id"] == item.id
    assert result[0]["retrieval_metadata"]["ownership_known"] is False
