"""Actual request activity and artifact-derived role status for the workbench."""

import os
from contextlib import ExitStack
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from time import monotonic

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from career.db import now, uid
from career.models import Artifact, ExecutionRun, PromptRun, Workspace
from career.provider_config import provider_available
from career.provider_policy import BudgetExceeded
from career.providers import ProviderUnavailable
from career.request_budget import check_deadline, deadline_scope
from career.runtime_trace import trace_context, trace_sink
from career.truth import owned

execution_id: ContextVar[str | None] = ContextVar("career_execution_id", default=None)

STAGES = (
    ("research", "기업·공고 조사", ("CompanyResearchResult",)),
    ("opportunity", "직무 분석", ("OpportunityBrief", "OpportunityAssessment")),
    ("evidence", "경험·근거 연결", ("EvidencePack",)),
    ("strategy", "지원 전략", ("ApplicationBrief", "QuestionPortfolio")),
    ("writing", "문항·이력서 작성", ("QuestionBrief", "Draft", "ResumeBrief", "ResumeContent")),
    ("review", "근거·채용 관점 검수", ("Review", "ResumeReview", "PortfolioReview")),
)
ACTION_STAGE = {
    "research": "research",
    "analyze": "opportunity",
    "assess-opportunity": "opportunity",
    "decide-opportunity": "opportunity",
    "evidence-map": "evidence",
    "strategy": "strategy",
    "approve-strategy": "strategy",
    "add-question": "writing",
    "question-brief": "writing",
    "approve-question": "writing",
    "generate": "writing",
    "resume": "writing",
    "patch": "writing",
    "revise": "review",
    "review": "review",
    "ledger": "review",
    "final-lock": "review",
    "ready": "review",
    "freeze": "review",
    "confirm": "review",
    "interview-handoff": "review",
    "close": "review",
    "correct-analysis": "opportunity",
    "question-portfolio": "strategy",
    "approve-portfolio": "strategy",
}
ACTION_LABELS = {
    "research": "기업·공고 자료 조사",
    "analyze": "실제 직무 산출물 분석",
    "evidence-map": "확인된 경험 연결",
    "strategy": "지원 전략 구성",
    "generate": "문항 본문 작성",
    "review": "문장과 근거 검수",
    "resume": "이력서 구성",
    "revise": "수정안 제안",
    "conversation": "대화 요청 처리",
    "commands": "다음 작업 처리",
    "freeze": "최종본 보관",
    "confirm": "실제 제출 확인",
    "interview-handoff": "면접 자료 구성",
    "approve-strategy": "지원 전략 승인",
    "approve-question": "문항 메시지 승인",
    "add-question": "문항 추가",
    "assess-opportunity": "지원 가치·우선순위 평가",
    "decide-opportunity": "지원 결정 기록",
    "question-brief": "문항 메시지 구성",
    "final-lock": "최종 문서 잠금",
    "patch": "직접 수정 반영",
    "ledger": "주장 근거 갱신",
    "ready": "최종 보관 조건 확인",
    "outcome": "전형 결과 기록",
    "postmortem": "지원 결과 회고",
    "close": "지원 추적 종료",
    "correct-analysis": "직무 해석 교정 반영",
    "question-portfolio": "문항별 역할 배분",
    "approve-portfolio": "문항 역할 승인",
}
AI_ACTIONS = frozenset({
    "conversation", "commands", "research", "analyze", "assess-opportunity", "evidence-map",
    "strategy", "question-portfolio", "question-brief", "generate", "review", "resume",
    "revise", "ready", "freeze", "interview-handoff", "postmortem",
})


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def recover_interrupted(db, user, workspace):
    # A bounded synchronous request cannot legitimately remain active forever.
    cutoff = now() - timedelta(seconds=int(os.getenv("EXECUTION_TIMEOUT_SECONDS", "900")))
    for run in db.scalars(
        select(ExecutionRun).where(
            ExecutionRun.user_id == user,
            ExecutionRun.workspace_id == workspace,
            ExecutionRun.status == "RUNNING",
        )
    ):
        if _utc(run.created_at) < cutoff:
            run.status, run.active_key, run.error_code = "FAILED", None, "EXECUTION_INTERRUPTED"
            run.finished_at = now()
            run.elapsed_ms = round((_utc(run.finished_at) - _utc(run.created_at)).total_seconds() * 1000)
            run.message = "연결이 끊긴 작업입니다. 현재 문서를 확인한 뒤 다시 실행해 주세요."


def run_operation(db, user, workspace, action, operation, uses_ai: bool | None = None):
    """Persist RUNNING before work; failed work rolls back, its status survives."""
    owned(db, Workspace, user, workspace)
    recover_interrupted(db, user, workspace)
    if db.scalar(
        select(ExecutionRun).where(
            ExecutionRun.user_id == user,
            ExecutionRun.workspace_id == workspace,
            ExecutionRun.active_key == "RUNNING",
        )
    ):
        raise ValueError("이 지원 작업이 아직 진행 중입니다. 완료된 뒤 다시 요청해 주세요.")
    run_ident = uid()
    run = ExecutionRun(
        id=run_ident,
        user_id=user,
        workspace_id=workspace,
        action=action,
        label=ACTION_LABELS.get(action, "작업 처리"),
        active_key="RUNNING",
        message="요청한 작업을 실행하고 있습니다.",
        data={"stage_key": ACTION_STAGE.get(action, "")},
    )
    db.add(run)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("이 지원 작업이 이미 진행 중입니다.") from exc
    token = execution_id.set(run_ident)
    traces = []

    def record_trace(stage, provider, data):
        entry = {"id": uid(), "stage": stage, "provider": provider, "data": data}
        traces.append(entry)
        db.add(PromptRun(user_id=user, **entry))

    sink_token = trace_sink.set(record_trace)
    context_token = trace_context.set({"execution_run_id": run_ident, "workspace_id": workspace})
    started = monotonic()
    budgets = ExitStack()
    try:
        budgets.enter_context(deadline_scope(100))
        if provider_available() and (uses_ai if uses_ai is not None else action in AI_ACTIONS):
            from career.usage_limits import request_budget_scope

            try:
                budgets.enter_context(request_budget_scope(db, user, action))
            except BudgetExceeded as exc:
                raise ProviderUnavailable(str(exc)) from None
        result = operation()
        try:
            check_deadline()
        except BudgetExceeded as exc:
            raise ProviderUnavailable(str(exc)) from None
        # Recovery revokes the lease. A slow original request must never commit
        # its artifacts after another request has recovered the execution.
        lease = db.scalar(
            select(ExecutionRun)
            .where(ExecutionRun.id == run.id, ExecutionRun.user_id == user)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if lease is None or lease.status != "RUNNING":
            raise ValueError("중단된 실행입니다. 현재 문서를 확인한 뒤 다시 요청해 주세요.")
        run = lease
        ws = owned(db, Workspace, user, workspace)
        response = result.get("data", {}).get("response", {}) if isinstance(result, dict) else {}
        if response.get("status") in {"NEEDS_INPUT", "ERROR", "NEEDS_USER_ACTION", "PROVIDER_UNAVAILABLE"}:
            run.status = "FAILED"
            run.error_code = response["status"]
        elif ws.state == "WAITING_STRATEGY_APPROVAL" or response.get("status") == "WAITING_REVIEW":
            run.status = "WAITING_USER"
        elif (
            isinstance(result, Artifact)
            and result.kind in {"QuestionBrief", "QuestionPortfolio"}
            and result.status == "ACTIVE"
        ):
            run.status = "WAITING_USER"
        else:
            run.status = "COMPLETED"
        run.message = {
            "COMPLETED": "작업 결과를 저장했습니다.",
            "WAITING_USER": "제안을 저장했습니다. 내용을 확인하고 승인해 주세요.",
            "FAILED": "현재 요청을 진행할 수 없습니다. 필요한 입력과 연결 상태를 확인해 주세요.",
        }[run.status]
        run.data = {**run.data, "workflow_state": ws.state}
        # Nested conversational rollback must not erase actual provider activity.
        for entry in traces:
            if db.get(PromptRun, entry["id"]) is None:
                db.add(PromptRun(user_id=user, **entry))
        return result
    except Exception as exc:
        db.rollback()
        run = owned(db, ExecutionRun, user, run.id)
        run.status = "FAILED"
        if run.error_code != "EXECUTION_INTERRUPTED":
            run.error_code = (
                "PROVIDER_UNAVAILABLE"
                if isinstance(exc, ProviderUnavailable)
                else "NEEDS_USER_ACTION"
                if isinstance(exc, ValueError)
                else "EXECUTION_FAILED"
            )
            run.message = "작업을 완료하지 못했습니다. 현재 문서와 필요한 입력을 확인해 주세요."
        run.active_key, run.finished_at = None, now()
        run.elapsed_ms = round((monotonic() - started) * 1000)
        for entry in traces:
            if db.get(PromptRun, entry["id"]) is None:
                db.add(PromptRun(user_id=user, **entry))
        db.commit()
        raise
    finally:
        try:
            budgets.close()
        finally:
            execution_id.reset(token)
            trace_sink.reset(sink_token)
            trace_context.reset(context_token)
        if run.status != "FAILED" or run.active_key:
            run.active_key, run.finished_at = None, now()
            run.elapsed_ms = round((monotonic() - started) * 1000)
            db.flush()


def serialize_run(run):
    return {
        "id": run.id,
        "action": run.action,
        "label": run.label,
        "status": run.status,
        "started_at": _utc(run.created_at).isoformat(),
        "finished_at": _utc(run.finished_at).isoformat() if run.finished_at else None,
        "elapsed_ms": run.elapsed_ms,
        "error_code": run.error_code,
        "message": run.message,
    }


def snapshot(db, user, workspace):
    from career.db import Record

    ws = owned(db, Workspace, user, workspace)
    recover_interrupted(db, user, workspace)
    latest = {}
    for item in db.scalars(
        select(Artifact)
        .where(Artifact.user_id == user, Artifact.workspace_id == workspace)
        .order_by(Artifact.version)
    ):
        latest[(item.kind, item.slot)] = item
    runs = list(
        db.scalars(
            select(ExecutionRun)
            .where(ExecutionRun.user_id == user, ExecutionRun.workspace_id == workspace)
            .order_by(ExecutionRun.created_at.desc())
            .limit(30)
        )
    )
    active = next((r for r in runs if r.status == "RUNNING"), None)
    stages = []
    for key, label, kinds in STAGES:
        items = [item for (kind, _), item in latest.items() if kind in kinds]
        representative = max(items, key=lambda a: (_utc(a.created_at), a.version)) if items else None
        status, detail = (
            ("DONE", "저장된 결과를 확인할 수 있습니다.")
            if items
            else ("NOT_STARTED", "아직 실행하지 않았습니다.")
        )
        if items and any(a.status in {"STALE", "INVALID"} for a in items):
            status, detail = "STALE", "근거 또는 기준이 바뀌어 다시 검토해야 합니다."
        elif key == "strategy" and items and ws.state == "WAITING_STRATEGY_APPROVAL":
            status, detail = "WAITING_USER", "지원 전략을 읽고 승인해 주세요."
        elif key == "strategy" and any(a.kind == "QuestionPortfolio" and a.status == "ACTIVE" for a in items):
            status, detail = "WAITING_USER", "문항별 역할과 메시지 후보를 승인해 주세요."
        elif key == "writing" and any(a.kind == "QuestionBrief" and a.status == "ACTIVE" for a in items):
            status, detail = "WAITING_USER", "문항 메시지 승인 후 본문을 작성합니다."
        elif key == "review" and items:
            if any(i.get("priority") in {"P0", "P1"} for a in items for i in a.data.get("issues", [])):
                status, detail = "FAILED", "최종 잠금 전 해결할 검수 문제가 있습니다."
            elif ws.state not in {"SUBMISSION_FROZEN", "SUBMITTED", "CLOSED", "READY_TO_FREEZE"}:
                status, detail = "WAITING_USER", "검수 결과와 최종 문서를 확인해 주세요."
        recent = next((r for r in runs if r.data.get("stage_key") == key), None)
        if active and active.data.get("stage_key") == key:
            status, detail = "RUNNING", active.label
        elif (
            recent
            and recent.status == "FAILED"
            and (representative is None or _utc(recent.created_at) >= _utc(representative.created_at))
        ):
            status, detail = "FAILED", recent.message
        stages.append(
            {
                "key": key,
                "label": label,
                "status": status,
                "detail": detail,
                "artifact_id": representative.id if representative else None,
                "artifact_version": representative.version if representative else None,
            }
        )
    pending = sum(
        1
        for r in db.scalars(
            select(Record).where(
                Record.user_id == user, Record.kind.in_(["RevisionProposal", "StructuredCorrectionProposal"])
            )
        )
        if r.data.get("workspace_id") == workspace and r.data.get("status") == "PENDING"
    )
    return {
        "workspace_id": ws.id,
        "workflow_state": ws.state,
        "provider": {
            "ai_available": provider_available(),
            "jev_enabled": bool(os.getenv("JEV_API_KEY") and os.getenv("JEV_SHADOW_ENABLED") == "1"),
        },
        "active_run": serialize_run(active) if active else None,
        "runs": [serialize_run(r) for r in runs],
        "stages": stages,
        "pending_review_count": pending,
    }


def bind_output(db, user, workspace, artifact):
    current = execution_id.get()
    for trace in db.scalars(select(PromptRun).where(PromptRun.user_id == user)):
        if (
            trace.data.get("execution_run_id") == current
            and trace.data.get("workspace_id") == workspace
            and trace.data.get("status", "COMPLETED") == "COMPLETED"
            and not trace.data.get("output_artifact_id")
        ):
            trace.data = {
                **trace.data,
                "output_artifact_id": artifact.id,
                "question_id": artifact.slot or None,
            }
