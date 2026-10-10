"""Version-bound responses to verification questions and recruiter risks.

Responses are derived review artifacts, never additions to Career Truth. Choosing
an action records intent; document/evidence changes still use their existing gates.
"""

from hashlib import sha256
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from career.artifacts import fresh, latest, lock, save
from career.claim_test import Citation
from career.schemas import Schema
from career.validation import hard_qa

if TYPE_CHECKING:
    from career.workflow import Workflow

ACTION_LABELS = {
    "ANSWER_WITH_EVIDENCE": "현재 근거로 답변",
    "REVISE_DOCUMENT": "문서에서 보완",
    "ADD_EVIDENCE": "근거 보완 후 재검수",
    "INTERVIEW_PREP": "면접에서 설명할 답변 준비",
    "ACKNOWLEDGE_GAP": "공백 인정과 대응",
}


class ResponseEntry(Schema):
    task_id: str = Field(min_length=1)
    action: Literal["ANSWER_WITH_EVIDENCE", "REVISE_DOCUMENT", "ADD_EVIDENCE", "INTERVIEW_PREP", "ACKNOWLEDGE_GAP"]
    answer: str = Field(min_length=1, max_length=10000)
    rationale: str = Field(min_length=1, max_length=5000)
    citations: list[Citation] = []


class ResponseRequest(Schema):
    review_id: str = Field(min_length=1)
    review_version: int = Field(ge=1)
    entries: list[ResponseEntry] = Field(min_length=1)
    confirmed: bool = False


class AnswerVerdict(Schema):
    task_id: str
    verdict: Literal["RESOLVED", "NEEDS_EVIDENCE", "NEEDS_REVISION"]
    rationale: str = Field(min_length=1)


class AnswerReview(Schema):
    items: list[AnswerVerdict]


class AnswerExtraction(Schema):
    entries: list[ResponseEntry]
    clarification: str = ""


def compile_tasks(reviews: list[tuple[str, dict]]) -> list[dict]:
    tasks = []
    for origin, review in reviews:
        details = {row["question"]: row["category"] for row in review.get("followup_details", [])}
        if len(details) != len(review.get("followup_details", [])) or not details.keys() <= set(review["followups"]):
            raise ValueError("검수 질문의 분류와 질문 목록을 일치시켜 주세요.")
        for index, question in enumerate(review["followups"]):
            if not question.strip():
                continue
            category = "GROUNDING" if origin == "fact_reviewer" else details.get(question, "GROUNDING")
            tasks.append({"id": sha256(f"{origin}:question:{index}:{question}".encode()).hexdigest()[:24],
                          "origin": origin, "kind": "QUESTION", "category": category,
                          "priority": "P1" if category == "GROUNDING" else "P2", "text": question})
        if origin == "recruiter":
            for index, issue in enumerate(review["issues"]):
                tasks.append({"id": sha256(f"{origin}:issue:{index}:{issue['message']}".encode()).hexdigest()[:24],
                              "origin": origin, "kind": "ISSUE", "category": "RECRUITER_RISK",
                              "priority": issue["priority"], "text": issue["message"], "issue_code": issue["code"]})
    return tasks


def tasks_for(review) -> list[dict]:
    # Older review records are not silently exempted from answering their questions.
    if "response_tasks" in review.data:
        return review.data["response_tasks"]
    return compile_tasks([("legacy_review", review.data)])


def current(service: "Workflow", workspace: str, qid="", resume=False):
    service.ws(workspace)
    document = service.artifact(workspace, "ResumeContent" if resume else "Draft", qid)
    review = service.artifact(workspace, "ResumeReview" if resume else "Review", qid)
    if document.id not in review.depends_on or review.data.get("document_version") != document.version:
        raise ValueError("현재 문서 버전의 검수를 먼저 실행해 주세요.")
    return document, review


def context(service: "Workflow", workspace: str, qid="", resume=False):
    document, review = current(service, workspace, qid, resume)
    return {"document_id": document.id, "review_id": review.id, "review_version": review.version,
            "tasks": tasks_for(review), "actions": ACTION_LABELS,
            "evidence": service.selected(document.data["selected_evidence_ids"])}


def saved_response(service: "Workflow", workspace: str, review, document):
    kind = "ResumeReviewResponses" if document.kind == "ResumeContent" else "ReviewResponses"
    previous = latest(service.db, service.user, workspace, kind, document.slot, required=False)
    if (previous and previous.status in {"ACTIVE", "LOCKED"}
            and previous.data.get("review_id") == review.id
            and previous.data.get("document_id") == document.id):
        fresh(service.db, service.user, previous)
        return previous
    return None


def from_message(service: "Workflow", workspace: str, qid: str, message: str, resume=False):
    service.editable(service.ws(workspace))
    document, review = current(service, workspace, qid, resume)
    previous = saved_response(service, workspace, review, document)
    draft = AnswerExtraction.model_validate(service.ai("review_answer_extract", {
        "message": message, "tasks": tasks_for(review),
        "previous_answers": previous.data["entries"] if previous else [],
        "evidence": service.selected(document.data["selected_evidence_ids"]),
        "document_domain": "RESUME" if resume else "COVER",
    }, AnswerExtraction))
    if not draft.entries:
        raise ValueError(draft.clarification or "어떤 검수 질문에 대한 답변인지 알려 주세요.")
    if any(entry.answer not in message for entry in draft.entries):
        raise ValueError("답변은 이번에 직접 적은 내용을 그대로 저장해야 합니다. 질문별 답변을 다시 확인해 주세요.")
    # Chat may interpret a response and ask the independent reviewer to check it;
    # it never manufactures human confirmation or writes a new canonical fact.
    return respond(service, workspace, qid, {
        "review_id": review.id, "review_version": review.version,
        "entries": [entry.model_dump() for entry in draft.entries], "confirmed": False,
    }, resume)


def respond(service: "Workflow", workspace: str, qid: str, payload: dict, resume=False, *, manual=False):
    ws = service.ws(workspace)
    service.editable(ws)
    request = ResponseRequest.model_validate(payload)
    document, review = current(service, workspace, qid, resume)
    if request.review_id != review.id or request.review_version != review.version:
        raise ValueError("검수 버전이 바뀌었습니다. 현재 질문을 다시 확인해 주세요.")
    if manual and not request.confirmed:
        raise ValueError("질문·답변과 원문을 직접 대조하고 확인해 주세요.")
    tasks = tasks_for(review)
    task_map = {task["id"]: task for task in tasks}
    if not tasks:
        raise ValueError("현재 검수에는 답변할 질문이나 채용 위험 지적이 없습니다.")
    requested_ids = {entry.task_id for entry in request.entries}
    if not requested_ids <= task_map.keys() or len(requested_ids) != len(request.entries):
        raise ValueError("현재 검수의 질문과 지적만 중복 없이 처리해 주세요.")
    previous = saved_response(service, workspace, review, document)
    evidence = service.selected(document.data["selected_evidence_ids"])
    from career.claim_test import validate_citations
    from career.truth import canonical

    profile = canonical(service.db, service.user)
    opportunity = service.artifact(workspace, "OpportunityBrief")
    strategy = service.artifact(workspace, "ApplicationBrief")
    rows, hard_issues = [], []
    for entry in request.entries:
        if not entry.answer.strip() or not entry.rationale.strip():
            raise ValueError("답변과 처리 이유를 입력해 주세요.")
        task = task_map[entry.task_id]
        citations = [citation.model_dump() for citation in entry.citations]
        validate_citations(evidence, citations)
        needs_proof = task["category"] == "GROUNDING" or entry.action == "ANSWER_WITH_EVIDENCE"
        action_pending = entry.action in {"REVISE_DOCUMENT", "ADD_EVIDENCE"}
        risk_blocked = task["kind"] == "ISSUE" and task["priority"] in {"P0", "P1"}
        if needs_proof and not action_pending and (entry.action != "ANSWER_WITH_EVIDENCE" or not citations):
            raise ValueError("사실 확인 질문은 원문 근거로 답하거나 문서·근거를 보완해야 합니다. 면접 대비로 넘길 수 없습니다.")
        issues = hard_qa(entry.answer, evidence, profile=profile, company_facts=opportunity.data.get("company_facts", []))
        hard_issues.extend({**issue, "task_id": entry.task_id} for issue in issues)
        rows.append({**entry.model_dump(), "status": "NEEDS_ACTION" if action_pending or risk_blocked or issues else "PENDING",
                     "verification_rationale": "문서 또는 근거 보완 뒤 현재 버전을 다시 검수해야 합니다." if action_pending or risk_blocked else "",
                     "task": task, "mode": "USER_VERIFIED" if manual else "AI_REVIEWED"})
    if not manual:
        output = AnswerReview.model_validate(service.ai("review_answers", {
            "document": document.data, "questions_and_answers": rows, "evidence": evidence,
            "canonical_profile": profile, "jd": ws.jd_raw, "opportunity": opportunity.data,
            "strategy": strategy.data, "document_domain": "RESUME" if resume else "COVER",
        }, AnswerReview)).model_dump()
        if {item["task_id"] for item in output["items"]} != requested_ids or len(output["items"]) != len(rows):
            raise ValueError("답변 검증 결과가 현재 질문 목록과 일치하지 않습니다.")
        for row in rows:
            verdict = next(item for item in output["items"] if item["task_id"] == row["task_id"])
            row["verification_rationale"] = verdict["rationale"]
            if row["status"] == "PENDING":
                row["status"] = "RESOLVED" if verdict["verdict"] == "RESOLVED" else "NEEDS_ACTION"
    else:
        for row in rows:
            if row["status"] == "PENDING":
                row["status"] = "RESOLVED"
                row["verification_rationale"] = "사용자가 원문과 답변을 직접 대조했습니다. " + row["rationale"]
    old_rows = {row["task_id"]: row for row in previous.data["entries"]} if previous else {}
    old_rows.update({row["task_id"]: row for row in rows})
    rows = [old_rows[task["id"]] for task in tasks if task["id"] in old_rows]
    unanswered = [task["id"] for task in tasks if task["id"] not in old_rows]
    if previous:
        hard_issues += [issue for issue in previous.data.get("hard_issues", [])
                        if issue.get("task_id") not in requested_ids]
    passed = not unanswered and all(row["status"] == "RESOLVED" for row in rows)
    modes = {row.get("mode", previous.data["mode"] if previous else "AI_REVIEWED") for row in rows}
    item, _ = save(service.db, service.user, workspace, "ResumeReviewResponses" if resume else "ReviewResponses", {
        "review_id": review.id, "review_version": review.version, "document_id": document.id,
        "document_version": document.version, "entries": rows, "hard_issues": hard_issues,
        "status": "RESOLVED" if passed else "NEEDS_ACTION", "mode": next(iter(modes)) if len(modes) == 1 else "MIXED_REVIEW",
        "unanswered_task_ids": unanswered,
        "fact_authority": False,
    }, slot=qid, deps=[document.id, review.id, opportunity.id, strategy.id],
       sources=sorted(set(service.reference_sources("review_answers", "RESUME" if resume else "COVER")
                          + [s for e in evidence for s in e["context_source_ids"]]
                          + [f["source_id"] for f in profile.values()])),
       model="manual" if manual else service.current_model)
    # A new answer changes what the user reviewed, even when prose is unchanged.
    # Require explicit final lock again without regenerating or discarding prose.
    for artifact in (document, review):
        if artifact.status == "LOCKED":
            artifact.status = "ACTIVE"
    no_blocker = not any(i["priority"] in {"P0", "P1"} for i in review.data["issues"])
    if resume:
        service.resume_state(workspace, "FINAL_READY" if passed and no_blocker else "REVIEWED")
    else:
        service.question_state(workspace, qid, "FINAL_READY" if passed and no_blocker else "QA_FAILED")
    ws.state = "REVIEWING"
    return item


def require_resolved(service: "Workflow", workspace: str, review, document, *, locking=False):
    if not tasks_for(review):
        return None
    kind = "ResumeReviewResponses" if document.kind == "ResumeContent" else "ReviewResponses"
    answers = latest(service.db, service.user, workspace, kind, document.slot, required=False)
    if answers is None:
        raise ValueError("검수 질문과 채용 위험 지적에 답변하고 처리 방법을 확인해 주세요.")
    fresh(service.db, service.user, answers)
    if (answers.data.get("review_id") != review.id or answers.data.get("document_id") != document.id
            or answers.data.get("status") != "RESOLVED"
            or {entry["task_id"] for entry in answers.data["entries"]} != {t["id"] for t in tasks_for(review)}):
        raise ValueError("현재 검수의 미해결 질문을 먼저 보완해 주세요.")
    if locking:
        lock(service.db, service.user, answers)
    return answers
