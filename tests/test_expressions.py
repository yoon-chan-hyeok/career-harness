import json
from copy import deepcopy

import pytest
from career.expressions import approve, context, listing, set_active
from career.models import Fact
from career.providers import FakeLLMProvider
from career.truth import add_evidence, register_source
from career.workflow import Workflow
from sqlalchemy import func, select
from test_api import client  # noqa: F401
from test_workflow import doc, finish, flow  # noqa: F401


def payload(document, **kwargs):
    return {"document_id": document.id, "excerpt": document.data["text"],
        "pattern_ids": ["JUDGMENT_FIRST"], "logic_pattern": ["관찰", "판단", "행동", "검증"],
        "tone_tags": ["담백함"], "scope": "QUESTION_TYPE", "confirmed": True, **kwargs}


def prepared(flow):
    f, w, e = flow
    q = finish(f, w, e)
    return f, w, e, q, f.artifact(w.id, "Draft", q["id"])


@pytest.mark.parametrize("field,value", [("confirmed", False), ("confirmed", "true"),
    ("pattern_ids", ["삼성에서 매출 200% 증가"]), ("logic_pattern", ["관찰", "원문 사실을 승인"]),
    ("tone_tags", ["원문을 사실로 승격"]), ("excerpt", "존재하지 않는 구절입니다.")])
def test_explicit_approval_literal_excerpt_and_fact_free_vocabulary_required(flow, field, value):  # noqa: F811
    f, w, _, _, document = prepared(flow)
    with pytest.raises(ValueError):
        approve(f, w.id, payload(document, **{field: value}))
    assert listing(f)["expressions"] == []


def test_approved_expression_is_not_truth_and_default_projection_excludes_old_numbers(flow):  # noqa: F811
    f, w, e, _, document = prepared(flow)
    before = f.db.scalar(select(func.count()).select_from(Fact))
    old = deepcopy(document.data)
    expression = approve(f, w.id, payload(document))
    assert expression.status == "LOCKED" and expression.data["authority"] == "EXPRESSION_ONLY"
    assert expression.data["excerpt"] == e.body and document.data == old
    assert f.db.scalar(select(func.count()).select_from(Fact)) == before
    projection = context(f, "COVER", "JOB_COMPETENCY", f.selected([e.id]))[0]
    assert projection["preferred_patterns"] and projection["logic_pattern"] == ["관찰", "판단", "행동", "검증"]
    assert "80%" not in json.dumps(projection, ensure_ascii=False)
    assert "current_evidence_excerpt" not in projection
    assert approve(f, w.id, payload(document)).id == expression.id
    with pytest.raises((ValueError, LookupError)):
        f.selected([expression.id])


def test_grounded_original_requires_same_current_evidence_and_is_removed_after_correction(flow):  # noqa: F811
    f, w, e, _, document = prepared(flow)
    approve(f, w.id, payload(document, allow_grounded_excerpt=True, scope="DOMAIN"))
    projection = context(f, "COVER", "OTHER", f.selected([e.id]))[0]
    assert projection["current_evidence_excerpt"]["text"] == e.body
    source, _ = register_source(f.db, "a", "unrelated", "새로운 프로젝트에서 인터페이스를 설계했습니다.", "RAW_RESULT")
    other = add_evidence(f.db, "a", source.id, "별도 경험", "새로운 프로젝트에서 인터페이스를 설계했습니다.", {}, "VERIFIED")
    assert "current_evidence_excerpt" not in context(f, "COVER", "OTHER", f.selected([other.id]))[0]
    e.data = {**e.data, "forbidden_claims": [e.body]}
    assert "current_evidence_excerpt" not in context(f, "COVER", "OTHER", f.selected([e.id]))[0]
    e.data = {**e.data, "forbidden_claims": []}
    document.status = "STALE"
    assert "current_evidence_excerpt" not in context(f, "COVER", "OTHER", f.selected([e.id]))[0]


def test_project_question_domain_and_owner_boundaries(flow):  # noqa: F811
    f, w, e, _, document = prepared(flow)
    approve(f, w.id, payload(document, scope="PROJECT", evidence_id=e.id))
    assert context(f, "COVER", "OTHER", []) == []
    assert context(f, "RESUME", "RESUME", f.selected([e.id])) == []
    assert context(Workflow(f.db, "b"), "COVER", "JOB_COMPETENCY", []) == []
    with pytest.raises(LookupError):
        approve(Workflow(f.db, "b"), w.id, payload(document))
    assert len(context(f, "COVER", "OTHER", f.selected([e.id]))) == 1
    approve(f, w.id, payload(document))
    assert context(f, "COVER", "MOTIVATION", f.selected([e.id])) == []
    assert len(context(f, "COVER", "", f.selected([e.id]), question="직무 역량을 설명하세요.")) == 1


def test_disable_is_versioned_and_does_not_change_locked_document_or_submission(flow):  # noqa: F811
    f, w, e, _, document = prepared(flow)
    expression = approve(f, w.id, payload(document))
    from final_review_fixture import confirm_final

    confirm_final(f, w.id)
    f.ready(w.id)
    bundle = f.freeze(w.id)
    frozen = deepcopy(bundle.data)
    inactive = set_active(f, expression.id, False)
    assert inactive.version == 2 and expression.status == "SUPERSEDED"
    assert context(f, "COVER", "JOB_COMPETENCY", f.selected([e.id])) == []
    assert document.status == "LOCKED" and bundle.data == frozen and w.state == "SUBMISSION_FROZEN"
    enabled = set_active(f, inactive.id, True)
    assert len(context(f, "COVER", "JOB_COMPETENCY", f.selected([e.id]))) == 1
    assert enabled.version == 3 and bundle.data == frozen
    with pytest.raises(LookupError):
        set_active(Workflow(f.db, "b"), enabled.id, False)


def test_unlocked_or_old_document_cannot_be_saved_as_approved_expression(flow):  # noqa: F811
    f, w, e, q, document = prepared(flow)
    f.draft(w.id, q["id"], doc(e))
    with pytest.raises(ValueError):
        approve(f, w.id, payload(document))
    with pytest.raises(ValueError):
        approve(f, w.id, payload(f.artifact(w.id, "Draft", q["id"])))


def test_cover_and_resume_writers_consume_approved_projection_and_record_usage(flow):  # noqa: F811
    f, w, e, q, document = prepared(flow)
    expression = approve(f, w.id, payload(document, allow_grounded_excerpt=True))
    class Spy(FakeLLMProvider):
        contexts = {}

        def structured(self, stage, context, schema):
            self.contexts[stage] = deepcopy(context)
            return super().structured(stage, context, schema)
    provider = Spy({"writer": doc(e)})
    f.provider = provider
    result = f.draft(w.id, q["id"])
    assert result.data["expression_usage"] == [{"expression_id": expression.id, "version": 1, "original_excerpt_rechecked": True}]
    assert provider.contexts["writer"]["style_projections"][0]["current_evidence_excerpt"]["text"] == e.body
    assert expression.status == "LOCKED" and result.status == "ACTIVE"  # no stale dependency cycle
    f.resume(w.id, doc(e))
    f.review(w.id, resume=True, manual_verified=True)
    resume = f.final_lock(w.id, resume=True)
    preferred = approve(f, w.id, payload(resume, scope="DOMAIN", pattern_ids=["OUTPUT_ACTION"]))
    provider = Spy({"resume_writer": {"sections": [{"title": "프로젝트", "kind": "PROJECT",
        "bullets": [{"text": e.body, "evidence_ids": [e.id], "claims": doc(e)["claims"]}]}]}})
    f.provider = provider
    new_resume = f.resume(w.id)
    assert new_resume.data["expression_usage"][0]["expression_id"] == preferred.id
    projection = provider.contexts["resume_writer"]["style_projections"]
    assert len(projection) == 1 and "산출물" in projection[0]["preferred_patterns"][0]
    assert "current_evidence_excerpt" not in projection[0]


def test_question_design_retrieves_matching_approved_structure(flow):  # noqa: F811
    f, w, e, q, document = prepared(flow)
    approve(f, w.id, payload(document))
    prior = deepcopy(f.artifact(w.id, "QuestionBrief", q["id"]).data)
    class Spy(FakeLLMProvider):
        projection = []

        def structured(self, stage, context, schema):
            self.projection = context["style_projections"]
            return super().structured(stage, context, schema)
    provider = Spy({"question_brief": prior})
    f.provider = provider
    f.question_brief(w.id, q["id"])
    assert provider.projection[0]["preferred_patterns"]


def test_expression_api_listing_and_mutation_are_isolated(client):  # noqa: F811
    from career.api import app, database

    with next(app.dependency_overrides[database]()) as db:
        f, w, e = getattr(flow, "__wrapped__")(db)
        q = finish(f, w, e)
        document = f.artifact(w.id, "Draft", q["id"])
        path = f"/api/applications/{w.id}/actions/expression-save"
        body = payload(document)
        db.commit()
    # The fixture owns its work under 'a', mapped explicitly for this request.
    import os
    os.environ["AUTH_TOKENS"] = json.dumps({"alice-key": "a", "bob-key": "b"})
    client.headers["Authorization"] = "Bearer alice-key"
    result = client.post(path, json=body, headers={"Idempotency-Key": "approved-expression-one"})
    assert result.status_code == 200, result.text
    duplicate = client.post(path, json=body, headers={"Idempotency-Key": "approved-expression-one"})
    assert duplicate.json()["id"] == result.json()["id"]
    assert len(client.get("/api/expressions").json()["expressions"]) == 1
    client.headers["Authorization"] = "Bearer bob-key"
    assert client.get("/api/expressions").json()["expressions"] == []
    assert client.post(path, json=body).status_code == 404
    assert client.patch("/api/expressions/" + result.json()["id"], json={"active": False}).status_code == 404
