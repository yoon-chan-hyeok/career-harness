"""Owner-scoped, deterministic v3 previews. No workflow executor or provider is called."""

import hashlib
import json
from typing import Literal

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from career.artifacts import fresh
from career.entities import ClaimBoundaryRecord, DecisionEpisodeRecord, MetricRecord, OwnershipRecord
from career.models import Artifact, Evidence, Source, Workspace
from career.truth import owned
from career.v3_contracts import CONTRACT_VERSION, Contract, Digest, ExperienceCard, Identifier, RevisionRef
from career.validation import GOOD

Intent = Literal["APPLICATION", "RESUME_ONLY", "INTERVIEW_ONLY"]
PreviewStatus = Literal[
    "PLANNED", "READY", "REUSE_CANDIDATE", "WAITING_EVIDENCE", "WAITING_APPROVAL",
    "BLOCKED", "NOT_APPLICABLE", "STALE",
]
RECORD_TYPES = (
    ("DECISION_EPISODE", DecisionEpisodeRecord), ("OWNERSHIP", OwnershipRecord),
    ("METRIC", MetricRecord), ("CLAIM_BOUNDARY", ClaimBoundaryRecord),
)


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), default=str).encode()).hexdigest()


def _read_only(db: Session):
    # Even a SELECT can autoflush caller changes; reject dirty sessions instead.
    if db.new or db.dirty or db.deleted:
        raise ValueError("미리보기 전에 현재 변경을 저장하거나 취소해 주세요.")


def _reference(kind, row) -> RevisionRef:
    values = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    return RevisionRef(kind=kind, id=row.id, revision=digest(values), status=row.status)


def experience_card(db: Session, user: str, evidence_id: str) -> ExperienceCard:
    _read_only(db)
    evidence = owned(db, Evidence, user, evidence_id)
    source = owned(db, Source, user, evidence.source_id)
    if evidence.kind == "EXPRESSION" or source.authority == "REFERENCE":
        raise ValueError("표현·규칙 자료를 경험 사실 카드로 사용할 수 없습니다.")
    refs, related_sources = [], {}
    for kind, model in RECORD_TYPES:
        records = db.scalars(select(model).where(
            model.user_id == user, model.evidence_id == evidence.id,
            model.status.not_in(["SUPERSEDED", "DO_NOT_USE"]),
        ).order_by(model.id))
        for record in records:
            if record.source_id:
                linked_source = owned(db, Source, user, record.source_id)
                related_sources[linked_source.id] = _reference("SOURCE", linked_source)
            refs.append(_reference(kind, record))
    evidence_ref, source_ref = _reference("EVIDENCE", evidence), _reference("SOURCE", source)
    warnings = []
    if evidence.status not in GOOD or source.status not in GOOD:
        warnings.append("경험 또는 출처가 미확인·충돌 상태입니다. 작성에 사용하기 전에 확인해야 합니다.")
    if any(ref.status not in GOOD for ref in refs):
        warnings.append("연결된 수행 범위·판단·수치 중 확인이 필요한 기록이 있습니다.")
    linked_sources = tuple(related_sources[key] for key in sorted(related_sources))
    if any(ref.status not in GOOD for ref in linked_sources):
        warnings.append("연결된 판단·수치 기록의 원자료를 다시 확인해야 합니다.")
    return ExperienceCard(
        owner_id=user, experience_id=evidence.id, title=evidence.title, body=evidence.body,
        evidence=evidence_ref, source=source_ref, related_sources=linked_sources,
        records=tuple(refs), warnings=tuple(warnings),
        revision=digest([user, evidence_ref.model_dump(), source_ref.model_dump(),
                         [ref.model_dump() for ref in refs], [ref.model_dump() for ref in linked_sources]]),
    )


class ArtifactSummary(Contract):
    id: Identifier
    kind: Identifier
    slot: str
    version: int = Field(ge=1)
    status: str
    current: bool


class NodePreview(Contract):
    id: Identifier
    kind: Identifier
    scope_id: Identifier
    label: str
    status: PreviewStatus
    reason: str
    depends_on: tuple[str, ...] = ()
    artifact: ArtifactSummary | None = None
    requires_human: bool = False
    budget_status: Literal["NOT_ESTIMATED", "NOT_REQUIRED"] = "NOT_REQUIRED"


class PlanPreview(Contract):
    contract_version: Literal["v3-preview-1"] = CONTRACT_VERSION
    mode: Literal["SHADOW_ONLY"] = "SHADOW_ONLY"
    owner_id: Identifier
    workspace_id: Identifier
    legacy_state: Identifier
    intent: Intent
    snapshot_revision: Digest
    plan_id: Digest
    nodes: tuple[NodePreview, ...]
    can_execute: Literal[False] = False
    completion_proof: Literal[False] = False
    notice: str = (
        "실행 없는 계획입니다. 기존 결과는 재사용 후보이며 승인·검수·완료 증명이 아닙니다. "
        "AI 입력 예산은 실제 요청 구성 후 검사해야 합니다. 최종 보관·제출은 기존 검증을 거쳐야 합니다."
    )


def application_plan(db: Session, user: str, workspace_id: str, intent: Intent = "APPLICATION") -> PlanPreview:
    _read_only(db)
    if intent not in {"APPLICATION", "RESUME_ONLY", "INTERVIEW_ONLY"}:
        raise ValueError("지원하지 않는 계획 종류입니다.")
    ws = owned(db, Workspace, user, workspace_id)
    rows = list(db.scalars(select(Artifact).where(
        Artifact.user_id == user, Artifact.workspace_id == ws.id,
    ).order_by(Artifact.kind, Artifact.slot, Artifact.version)))
    latest: dict[tuple[str, str], Artifact] = {}
    summaries = {}
    for row in rows:
        latest[(row.kind, row.slot)] = row
    for key, row in latest.items():
        try:
            fresh(db, user, row)
            current = True
        except (ValueError, LookupError):
            current = False
        summaries[key] = ArtifactSummary(id=row.id, kind=row.kind, slot=row.slot, version=row.version,
                                         status=row.status, current=current)

    # Bind the plan to the versions it observed; never put source prose in logs.
    source_ids = {ident for row in rows for ident in row.source_ids}
    evidence_ids = set()
    for row in latest.values():
        for field in ("evidence_ids", "selected_evidence_ids"):
            evidence_ids.update(row.data.get(field, []))
        if row.kind == "EvidencePack":
            evidence_ids.update(item["evidence_id"] for item in row.data.get("items", []))
    truth_refs = []
    missing_truth = False
    for ident in sorted(evidence_ids):
        try:
            card = experience_card(db, user, ident)
            truth_refs.append([ident, card.revision])
            missing_truth = missing_truth or bool(card.warnings)
        except (LookupError, ValueError):
            missing_truth = True
            truth_refs.append(["unavailable", digest([user, ident])])
    for ident in sorted(source_ids):
        try:
            source = owned(db, Source, user, ident)
            truth_refs.append(_reference("SOURCE", source).model_dump())
        except LookupError:
            missing_truth = True
            truth_refs.append(["unavailable-source", digest([user, ident])])
    revision = digest([user, ws.id, ws.state, ws.mode, ws.jd_raw, ws.data,
                       [[r.id, r.version, r.status, r.data, r.depends_on, r.source_ids] for r in rows],
                       [summary.model_dump() for summary in summaries.values()], truth_refs])
    nodes: list[NodePreview] = []

    def add(kind, label, deps=(), artifact_kind=None, slot="", human=False, llm=False,
            forced: PreviewStatus | None = None, reason=""):
        scope = slot or ws.id
        node_id = digest([user, ws.id, scope, kind, CONTRACT_VERSION])
        summary = summaries.get((artifact_kind, slot)) if artifact_kind else None
        parents = [node for node in nodes if node.id in deps]
        result = latest.get((artifact_kind, slot)) if artifact_kind else None
        failed_qa = result is not None and summary is not None and summary.current and (
            (artifact_kind in {"Review", "ResumeReview"} and any(
                issue.get("priority") in {"P0", "P1"} for issue in result.data.get("issues", [])
            )) or (artifact_kind == "ClaimEvidenceTest" and result.data.get("result") != "PASSED")
        )
        if result and summary and summary.current and artifact_kind == "ClaimEvidenceTest":
            brief = latest.get(("QuestionBrief", slot))
            failed_qa = failed_qa or brief is None or (
                result.data.get("brief_id") != brief.id
                or result.data.get("brief_version") != brief.version or brief.id not in result.depends_on
            )
        if result and summary and summary.current and artifact_kind in {"Review", "ResumeReview"}:
            document_kind = "ResumeContent" if artifact_kind == "ResumeReview" else "Draft"
            document = latest.get((document_kind, slot))
            failed_qa = failed_qa or document is None or (
                document.id not in result.depends_on or result.data.get("document_version") != document.version
            )
            if not failed_qa and document is not None:
                from career.review_resolution import tasks_for

                tasks = tasks_for(result)
                if tasks:
                    answer_kind = "ResumeReviewResponses" if artifact_kind == "ResumeReview" else "ReviewResponses"
                    answers, answer_summary = latest.get((answer_kind, slot)), summaries.get((answer_kind, slot))
                    failed_qa = answers is None or answer_summary is None or not answer_summary.current or (
                        answers.data.get("review_id") != result.id
                        or answers.data.get("document_id") != document.id
                        or answers.data.get("status") != "RESOLVED"
                        or {entry.get("task_id") for entry in answers.data.get("entries", [])}
                        != {task["id"] for task in tasks}
                    )
        if forced:
            status = forced
        elif failed_qa:
            status, reason = "BLOCKED", "실패한 현재 검수·근거 검사를 보완한 뒤 다시 확인해야 합니다."
        elif summary and not summary.current:
            status, reason = "STALE", "이전 결과나 연결 근거가 바뀌어 재검토가 필요합니다."
        elif any(node.status not in {"REUSE_CANDIDATE", "NOT_APPLICABLE"} for node in parents):
            status, reason = "PLANNED", "선행 자료·검사·승인을 확인한 뒤 진행할 후보 단계입니다."
        elif summary:
            status = "WAITING_APPROVAL" if human and summary.status != "LOCKED" else "REUSE_CANDIDATE"
            reason = ("현재 제안을 읽고 명시적으로 승인해야 합니다." if status == "WAITING_APPROVAL"
                      else "현재 버전의 결과가 있습니다. 실행 시 기존 검사로 유효성을 다시 확인해야 합니다.")
        elif human:
            status, reason = "WAITING_APPROVAL", "사람의 명시적 확인이 필요한 단계입니다."
        else:
            status, reason = "READY", "실행 전 입력·권한·예산 검사가 필요한 작업 후보입니다."
        node = NodePreview(id=node_id, kind=kind, scope_id=scope, label=label, status=status,
                           reason=reason, depends_on=tuple(deps), artifact=summary, requires_human=human,
                           budget_status="NOT_ESTIMATED" if llm else "NOT_REQUIRED")
        nodes.append(node)
        return node.id

    bundle = summaries.get(("SubmissionBundle", ""))
    if intent == "INTERVIEW_ONLY":
        snapshot = add("SUBMISSION_SNAPSHOT", "제출 보관본 확인", artifact_kind="SubmissionBundle",
                       forced=None if bundle and bundle.current and bundle.status == "LOCKED"
                       else "WAITING_EVIDENCE", reason="면접 준비에 사용할 잠긴 제출 보관본이 필요합니다.")
        add("INTERVIEW_PREP", "제출본 기반 면접 준비", (snapshot,), "InterviewHandoff", llm=True)
        add("DOCUMENT_COMPOSITION", "자소서·레쥬메 생성", forced="NOT_APPLICABLE",
            reason="면접 준비 요청에는 새 문서 생성을 포함하지 않습니다.")
    elif ws.state in {"SUBMISSION_FROZEN", "SUBMITTED", "CLOSED"}:
        add("PRESERVE_SNAPSHOT", "기존 보관본 보존", artifact_kind="SubmissionBundle",
            forced="REUSE_CANDIDATE" if bundle and bundle.current else "WAITING_EVIDENCE",
            reason="이 작업의 보관본은 변경하지 않습니다. 문서 수정은 새 지원 작업에서 진행합니다.")
        add("DOCUMENT_COMPOSITION", "기존 지원서 변경", forced="BLOCKED",
            reason="동결·제출·종료된 작업의 문서를 다시 생성하지 않습니다.")
        if ws.state == "SUBMISSION_FROZEN":
            add("SUBMISSION_CONFIRMATION", "실제 제출 확인", human=True,
                forced="WAITING_APPROVAL", reason="보관은 실제 제출이 아닙니다. 본인의 제출 확인이 필요합니다.")
    else:
        research = add("RESEARCH", "회사 자료 확인", artifact_kind="CompanyResearchResult", llm=True)
        research_review = add("RESEARCH_APPROVAL", "조사 범위·채용 배경 확인", (research,),
                              "ResearchReview", human=True)
        job = add("JOB_REALITY", "공고·본업·산출물 분석", (research_review,), "OpportunityBrief", llm=True)
        mapping = add("EVIDENCE_MAPPING", "경험 근거 연결", (job,), "EvidencePack", llm=True,
                      forced="WAITING_EVIDENCE" if missing_truth else None,
                      reason="선택 근거나 연결 기록을 현재 소유자의 유효한 자료로 다시 확인해야 합니다.")
        assessment = latest.get(("OpportunityAssessment", ""))
        assessment_summary = summaries.get(("OpportunityAssessment", ""))
        eligibility: PreviewStatus | None = None
        eligibility_reason = ""
        if assessment and assessment_summary and assessment_summary.current:
            checks = assessment.data.get("eligibility", [])
            decision = ws.data.get("opportunity_decision", {})
            human_hold = decision.get("artifact_id") == assessment.id and decision.get("decision") in {"HOLD", "SKIP"}
            if human_hold or assessment.data.get("recommendation") == "SKIP" or any(
                item.get("status") == "NOT_MET" for item in checks
            ):
                eligibility, eligibility_reason = "BLOCKED", "현재 자격 미충족·지원 보류 판단을 먼저 확인해야 합니다."
            elif any(item.get("status") != "MET" for item in checks):
                eligibility = "WAITING_EVIDENCE"
                eligibility_reason = "미확인 지원 자격을 먼저 확인해야 합니다."
        eligible = add("ELIGIBILITY", "지원 자격과 공백 확인", (mapping,), "OpportunityAssessment", llm=True,
                       forced=eligibility, reason=eligibility_reason)
        strategy = add("STRATEGY", "지원 전략 제안", (eligible,), "ApplicationBrief", llm=True)
        approval = add("STRATEGY_APPROVAL", "지원 전략 승인", (strategy,), "ApplicationBrief", human=True)
        questions = ws.data.get("questions", []) if intent == "APPLICATION" else []
        requested_resume = intent == "RESUME_ONLY" or ws.data.get("resume_requested") is True
        if len(questions) > 1:
            allocation = add("QUESTION_PORTFOLIO", "문항 역할·소재 배분", (approval,), "QuestionPortfolio", llm=True)
            allocation = add("PORTFOLIO_APPROVAL", "문항 배분 승인", (allocation,), "QuestionPortfolio", human=True)
        else:
            allocation = approval
            add("QUESTION_PORTFOLIO", "다문항 배분", forced="NOT_APPLICABLE",
                reason="이번 요청의 자소서 문항이 두 개 미만입니다. 전략·주장 승인은 별도로 유지합니다.")
        locks = []
        for question in questions:
            qid = question["id"]
            brief = add("CLAIM_PLAN", "문항 메시지·구성 설계", (allocation,), "QuestionBrief", qid, llm=True)
            proof = add("EVIDENCE_TEST", "주장 근거 검사", (brief,), "ClaimEvidenceTest", qid, llm=True)
            claim = add("CLAIM_APPROVAL", "문항 메시지 승인", (proof,), "QuestionBrief", qid, human=True)
            draft = add("DRAFT", "문항 초안", (claim,), "Draft", qid, llm=True)
            review = add("DOCUMENT_QA", "문항 검수·필수 답변 확인", (draft,), "Review", qid, llm=True)
            locks.append(add("DOCUMENT_LOCK", "문항 최종 잠금", (review,), "Draft", qid, human=True))
        if not questions:
            add("COVER_COMPOSITION", "자소서 문항 작성", forced="NOT_APPLICABLE" if requested_resume
                else "WAITING_EVIDENCE", reason="레쥬메만 작성하는 요청입니다." if requested_resume
                else "작성할 자소서 문항 또는 레쥬메 요청이 필요합니다.")
        if requested_resume:
            resume = add("RESUME_COMPOSITION", "레쥬메 작성", (approval,), "ResumeContent", llm=True)
            review = add("RESUME_QA", "레쥬메 검수·필수 답변 확인", (resume,), "ResumeReview", llm=True)
            locks.append(add("RESUME_LOCK", "레쥬메 최종 잠금", (review,), "ResumeContent", human=True))
        readiness = add("SUBMISSION_READINESS", "요청한 전체 문서 최종 확인", tuple(locks),
                        forced="BLOCKED" if not locks else "PLANNED",
                        reason="기존 ready()로 등록된 모든 문서·최신 검수·필수 답변을 다시 검사해야 합니다.")
        frozen = add("SUBMISSION_FREEZE", "제출본 보관 승인", (readiness,), human=True)
        add("SUBMISSION_CONFIRMATION", "실제 제출 확인", (frozen,), human=True)
    return PlanPreview(owner_id=user, workspace_id=ws.id, legacy_state=ws.state, intent=intent,
                       snapshot_revision=revision, plan_id=digest([CONTRACT_VERSION, user, intent, revision]),
                       nodes=tuple(nodes))
