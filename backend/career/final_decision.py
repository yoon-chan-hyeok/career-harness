"""Human review of the role noun and three final questions; never invent intent."""
import hashlib
import json
from typing import Literal

from pydantic import Field, StrictBool

from career.artifacts import latest, save
from career.db import now
from career.schemas import Schema
from career.truth import view

KIND = "FinalSubmissionReview"


class Citation(Schema):
    evidence_id: str
    quote: str = Field(min_length=4, max_length=2000)


class Decision(Schema):
    context_hash: str
    role_noun: str = Field(min_length=2, max_length=120)
    role_alignment: Literal["MATCH", "MISMATCH", "UNCERTAIN"]
    assignment_answer: str = Field(min_length=15, max_length=2000)
    motivation_answer: str = Field(min_length=15, max_length=2000)
    wants_core_work: StrictBool
    evidence_answer: str = Field(min_length=15, max_length=2000)
    citations: list[Citation] = Field(min_length=1, max_length=6)
    gaps_answer: str = Field(min_length=8, max_length=2000)
    decision: Literal["PASS", "REVISE"]
    return_stage: Literal["NONE", "ANALYSIS", "STRATEGY", "EVIDENCE", "WRITING"]
    confirmed: StrictBool = False


def inputs(service, workspace: str):
    ws = service.ws(workspace)
    opportunity = service.artifact(workspace, "OpportunityBrief")
    strategy = service.artifact(workspace, "ApplicationBrief")
    pack = service.artifact(workspace, "EvidencePack")
    if strategy.status != "LOCKED":
        raise ValueError("현재 지원 전략을 먼저 승인해 주세요.")
    dependencies = [opportunity, strategy, pack]
    documents = []
    for question in ws.data.get("questions", []):
        dependencies.append(service.artifact(workspace, "QuestionBrief", question["id"]))
        documents.append(service.artifact(workspace, "Draft", question["id"]))
        dependencies.append(service.artifact(workspace, "Review", question["id"]))
    if ws.data.get("resume_requested"):
        documents.append(service.artifact(workspace, "ResumeContent"))
        dependencies.append(service.artifact(workspace, "ResumeReview"))
    if not documents or any(item.status != "LOCKED" for item in documents + dependencies[3:]):
        raise ValueError("요청한 문서와 검수를 모두 최종 잠근 후 마지막 세 질문을 확인해 주세요.")
    dependencies += documents
    selected = service.selected(sorted({i for doc in documents for i in doc.data["selected_evidence_ids"]}))
    proof = [{k: e[k] for k in ("id", "title", "body", "source_id", "status", "data")} for e in selected]
    state = {"artifact_ids": sorted(a.id for a in dependencies), "evidence": proof,
             "artifacts": [{"id": a.id, "status": a.status, "data": a.data} for a in dependencies],
             "questions": ws.data.get("questions", []), "resume_requested": ws.data.get("resume_requested", False)}
    digest = hashlib.sha256(json.dumps(state, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
    return {"context_hash": digest, "artifact_ids": state["artifact_ids"],
            "base_profession": opportunity.data["base_profession"], "actual_outputs": opportunity.data["actual_outputs"],
            "assignment_statement": strategy.data["assignment_statement"],
            "fatal_gaps": strategy.data.get("fatal_gaps", []), "selection_risks": strategy.data.get("selection_risks", []),
            "evidence_mapping": pack.data["items"], "evidence": selected,
            "documents": [{"id": doc.id, "kind": doc.kind, "slot": doc.slot, "version": doc.version,
                           "text": doc.data["text"]} for doc in documents]}


def context(service, workspace: str):
    current = inputs(service, workspace)
    prior = latest(service.db, service.user, workspace, KIND, required=False)
    return {**current, "previous": view(prior) if prior else None,
            "current_pass": bool(prior and prior.status == "LOCKED" and prior.data["decision"] == "PASS"
                                 and prior.data["context_hash"] == current["context_hash"])}


def confirm(service, workspace: str, payload: dict):
    ws = service.ws(workspace)
    service.editable(ws)
    entry = Decision.model_validate(payload)
    current = inputs(service, workspace)
    if not entry.confirmed:
        raise ValueError("현재 문서와 근거를 읽고 마지막 세 질문을 직접 확인해 주세요.")
    if entry.context_hash != current["context_hash"]:
        raise ValueError("확인 중 문서·전략·근거가 바뀌었습니다. 현재 내용을 다시 확인해 주세요.")
    for key in ("role_noun", "assignment_answer", "motivation_answer", "evidence_answer", "gaps_answer"):
        value = getattr(entry, key)
        minimum = 2 if key == "role_noun" else 8 if key == "gaps_answer" else 15
        if len(value.strip()) < minimum:
            raise ValueError("세 질문과 남은 공백에 구체적으로 답해 주세요.")
    evidence = {e["id"]: e for e in current["evidence"]}
    for citation in entry.citations:
        item = evidence.get(citation.evidence_id)
        if item is None or len(citation.quote.strip()) < 4 or citation.quote not in item["body"]:
            raise ValueError("현재 문서에서 선택한 근거의 원문을 정확히 인용해 주세요.")
    if entry.decision == "PASS":
        if entry.role_alignment != "MATCH" or not entry.wants_core_work or entry.return_stage != "NONE":
            raise ValueError("본업 정체성과 지원 의향에 의문이 있으면 돌아갈 단계를 골라 보완으로 기록해 주세요.")
        if " ".join(entry.role_noun.split()).casefold() != " ".join(current["base_profession"].split()).casefold():
            raise ValueError("문서를 읽고 떠오르는 직업 명칭이 분석한 본업과 다릅니다. 분석 또는 문서를 먼저 보완해 주세요.")
    elif entry.return_stage == "NONE":
        raise ValueError("보완할 단계를 선택해 주세요.")
    data = {**entry.model_dump(exclude={"confirmed"}), "verification_method": "USER_REVIEW",
            "base_profession": current["base_profession"], "document_ids": [d["id"] for d in current["documents"]],
            "reviewed_at": now().isoformat(), "authority": "DECISION_NOT_CANDIDATE_FACT"}
    previous = latest(service.db, service.user, workspace, KIND, required=False)
    if previous and previous.status == "LOCKED" and all(previous.data.get(k) == v for k, v in data.items() if k != "reviewed_at"):
        return previous
    result, _ = save(service.db, service.user, workspace, KIND, data, deps=current["artifact_ids"],
                     sources=sorted({e["source_id"] for e in current["evidence"]}))
    result.status = "LOCKED"
    # A confirmed decision does not freeze or submit; ready() still runs all QA.
    ws.state = "REVIEWING" if entry.decision == "PASS" else "NEED_USER_ACTION"
    return result


def require_pass(service, workspace: str):
    record = latest(service.db, service.user, workspace, KIND, required=False)
    if record is None or record.status != "LOCKED" or record.data.get("decision") != "PASS":
        raise ValueError("검수·제출에서 직업 정체성과 마지막 세 질문을 직접 확인해 주세요.")
    current = inputs(service, workspace)
    if record.data["context_hash"] != current["context_hash"]:
        raise ValueError("마지막 확인 이후 문서·전략·근거가 바뀌었습니다. 세 질문을 다시 확인해 주세요.")
    service.artifact(workspace, KIND)
    return record
