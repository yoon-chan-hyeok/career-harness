# ruff: noqa: F811 -- reusable workflow fixture
import pytest
from career.human_review import resolve
from test_workflow import doc, flow  # noqa: F401


@pytest.mark.parametrize(("pages", "budget"), [(1, 3500), (2, 7000), ("MASTER", 20000)])
def test_resume_compression_uses_selected_budget_and_still_requires_approval_and_review(flow, pages, budget):
    service, workspace, evidence = flow
    service.approve_strategy(workspace.id)
    original = doc(evidence)
    original["text"] = evidence.body * (budget // len(evidence.body) + 2)
    original["claims"][0]["text"] = original["text"]
    document = service.resume(workspace.id, original, page_budget=pages)
    review = service.review(workspace.id, resume=True, manual_verified=True)
    assert any(issue["code"] == "CHAR_LIMIT" for issue in review.data["issues"])
    captured = {}

    class Compressor:
        def structured(self, stage, context, schema):
            assert stage == "issue_patch_compression"
            captured.update(context)
            return schema.model_validate({
                "old_text": original["text"], "new_text": evidence.body,
                "claims": doc(evidence)["claims"], "issue_codes": ["CHAR_LIMIT"],
            })

    service.provider = Compressor()
    proposal = service.revise(workspace.id, "", resume=True)
    assert captured["character_limit"] == budget
    assert captured["document_domain"] == "RESUME"
    assert service.artifact(workspace.id, "ResumeContent").id == document.id
    resolve(service, workspace.id, proposal["id"], "ACCEPT")
    revised = service.artifact(workspace.id, "ResumeContent")
    assert revised.data["character_budget"] == budget and revised.data["text"] == evidence.body
    assert review.status == "STALE"
    with pytest.raises(ValueError):
        service.final_lock(workspace.id, resume=True)
    checked = service.review(workspace.id, resume=True, manual_verified=True)
    assert not any(issue["code"] == "CHAR_LIMIT" for issue in checked.data["issues"])
    service.final_lock(workspace.id, resume=True)
    assert revised.status == "LOCKED"
