"""Stable REST contract aliases over the same application service."""

from typing import Annotated, Any

from fastapi import APIRouter, Header

from career.api import DB, User, action
from career.truth import view
from career.workflow import Workflow

router = APIRouter()
RequestKey = Annotated[str | None, Header(alias="Idempotency-Key")]


@router.post("/api/opportunities/{workspace}/research")
def research(workspace: str, body: dict[str, Any], db: DB, ident: User, key: RequestKey = None):
    return action(workspace, "research", body, db, ident, key)


@router.post("/api/opportunities/{workspace}/analyze")
def analyze(workspace: str, body: dict[str, Any], db: DB, ident: User, key: RequestKey = None):
    return action(workspace, "analyze", body, db, ident, key)


@router.patch("/api/opportunities/{workspace}/evidence-map")
def evidence_map(workspace: str, body: dict[str, Any], db: DB, ident: User, key: RequestKey = None):
    return action(workspace, "evidence-map", body, db, ident, key)


@router.get("/api/opportunities/{workspace}/brief")
def brief(workspace: str, db: DB, ident: User):
    return view(Workflow(db, ident).artifact(workspace, "OpportunityBrief"))


@router.get("/api/opportunities/{workspace}/evidence-pack")
def pack(workspace: str, db: DB, ident: User):
    return view(Workflow(db, ident).artifact(workspace, "EvidencePack"))


@router.post("/api/applications/{workspace}/strategy")
def strategy(workspace: str, body: dict[str, Any], db: DB, ident: User, key: RequestKey = None):
    return action(workspace, "strategy", body, db, ident, key)


@router.post("/api/applications/{workspace}/approve-strategy")
def approve_strategy(workspace: str, body: dict[str, Any], db: DB, ident: User, key: RequestKey = None):
    return action(workspace, "approve-strategy", body, db, ident, key)


@router.post("/api/applications/{workspace}/questions/{qid}/brief")
@router.patch("/api/applications/{workspace}/questions/{qid}/brief")
def question_brief(workspace: str, qid: str, body: dict[str, Any], db: DB, ident: User, key: RequestKey = None):
    return action(workspace, "question-brief", {**body, "qid": qid}, db, ident, key)


@router.post("/api/applications/{workspace}/questions/{qid}/approve")
def approve_question(workspace: str, qid: str, body: dict[str, Any], db: DB, ident: User, key: RequestKey = None):
    return action(workspace, "approve-question", {**body, "qid": qid}, db, ident, key)


@router.post("/api/applications/{workspace}/questions/{qid}/evidence-test")
def evidence_test(workspace: str, qid: str, body: dict[str, Any], db: DB, ident: User, key: RequestKey = None):
    return action(workspace, "claim-test", {**body, "qid": qid}, db, ident, key)


@router.get("/api/applications/{workspace}/questions/{qid}/evidence-test-context")
def evidence_test_context(workspace: str, qid: str, db: DB, ident: User):
    from career.claim_test import CHECKS, claim_texts

    service = Workflow(db, ident)
    service.ws(workspace)
    brief = service.artifact(workspace, "QuestionBrief", qid)
    return {"brief_id": brief.id, "brief_version": brief.version, "claims": claim_texts(brief.data),
            "checks": CHECKS, "evidence": service.selected(brief.data["evidence_ids"])}


@router.post("/api/applications/{workspace}/questions/{qid}/generate")
def generate(workspace: str, qid: str, body: dict[str, Any], db: DB, ident: User, key: RequestKey = None):
    return action(workspace, "generate", {**body, "qid": qid}, db, ident, key)


@router.post("/api/applications/{workspace}/questions/{qid}/review")
def review(workspace: str, qid: str, body: dict[str, Any], db: DB, ident: User, key: RequestKey = None):
    return action(workspace, "review", {**body, "qid": qid}, db, ident, key)


@router.post("/api/applications/{workspace}/resume/generate")
def resume(workspace: str, body: dict[str, Any], db: DB, ident: User, key: RequestKey = None):
    return action(workspace, "resume", body, db, ident, key)


@router.get("/api/applications/{workspace}/review-response-context")
def review_response_context(workspace: str, db: DB, ident: User, qid: str = "", resume: bool = False):
    from career.review_resolution import context

    return context(Workflow(db, ident), workspace, qid, resume)


@router.post("/api/applications/{workspace}/submission/freeze")
def freeze(workspace: str, body: dict[str, Any], db: DB, ident: User, key: RequestKey = None):
    return action(workspace, "freeze", body, db, ident, key)


@router.post("/api/applications/{workspace}/submission/confirm")
def confirm(workspace: str, body: dict[str, Any], db: DB, ident: User, key: RequestKey = None):
    return action(workspace, "confirm", body, db, ident, key)


@router.post("/api/applications/{workspace}/interview-handoff")
def handoff(workspace: str, body: dict[str, Any], db: DB, ident: User, key: RequestKey = None):
    return action(workspace, "interview-handoff", body, db, ident, key)


@router.post("/api/applications/{workspace}/close")
def close_application(workspace: str, body: dict[str, Any], db: DB, ident: User,
                      idempotency_key: Annotated[str | None, Header()] = None):
    return action(workspace, "close", body, db, ident, idempotency_key)


@router.get("/api/applications/{workspace}/interview-handoff")
def handoff_read(workspace: str, db: DB, ident: User):
    return view(Workflow(db, ident).artifact(workspace, "InterviewHandoff"))


@router.post("/api/applications/{workspace}/commands")
def commands(workspace: str, body: dict[str, Any], db: DB, ident: User, key: RequestKey = None):
    return action(workspace, "commands", body, db, ident, key)


@router.post("/api/applications/{workspace}/outcome")
def outcome(workspace: str, body: dict[str, Any], db: DB, ident: User, key: RequestKey = None):
    return action(workspace, "outcome", body, db, ident, key)


@router.post("/api/applications/{workspace}/postmortem")
def postmortem(workspace: str, body: dict[str, Any], db: DB, ident: User, key: RequestKey = None):
    return action(workspace, "postmortem", body, db, ident, key)
