import pytest
from test_workflow import doc, finish, flow, question  # noqa: F401


def test_regeneration_cannot_erase_protected_text(flow):  # noqa: F811
    f, w, e = flow
    q = finish(f, w, e)
    f.patch_document(w.id, q["id"], "", "", protected=["80%"])
    new = doc(e)
    new["text"] = "실험을 설계했습니다."
    new["claims"][0]["text"] = new["text"]
    with pytest.raises(ValueError, match="보호"):
        f.draft(w.id, q["id"], new)


def test_automatic_revision_cap(flow):  # noqa: F811
    f, w, e = flow
    q = finish(f, w, e)
    first = f.artifact(w.id, "Draft", q["id"])
    f.patch_document(w.id, q["id"], "직접", "스스로", automatic=True)
    f.patch_document(w.id, q["id"], "스스로", "직접", automatic=True)
    assert first.status == "SUPERSEDED"
    with pytest.raises(ValueError, match="2회"):
        f.patch_document(w.id, q["id"], "직접", "스스로", automatic=True)


def test_lock_command_approves_current_brief(flow):  # noqa: F811
    f, w, e = flow
    f.command(w.id, "잠가")
    assert w.state == "STRATEGY_LOCKED"
    q = question(f, w, e)
    f.command(w.id, "잠가", qid=q["id"])
    assert f.artifact(w.id, "QuestionBrief", q["id"]).status == "LOCKED"


def test_remove_last_evidence_applies_correction_and_blocks_writing(flow):  # noqa: F811
    f, w, e = flow
    q = finish(f, w, e)
    result = f.command(w.id, "RAG 빼", qid=q["id"])
    assert result["patched_artifacts"]
    assert w.state == "NEED_USER_ACTION"
    with pytest.raises(ValueError):
        f.approve_question(w.id, q["id"])


def test_go_after_locked_document_only_prepares_not_submits(flow):  # noqa: F811
    f, w, e = flow
    q = finish(f, w, e)
    f.command(w.id, "ㄱㄱ", qid=q["id"])
    assert w.state == "READY_TO_FREEZE"
