"""Conversation adapter: artifacts own state, messages record interaction only."""

from typing import Literal

from pydantic import Field
from sqlalchemy import select

from career.artifacts import latest
from career.db import Record
from career.models import Artifact
from career.provider_config import provider_available
from career.providers import ProviderUnavailable
from career.schemas import OutputImportance, Schema
from career.truth import view
from career.workflow import Workflow


class ChatRequest(Schema):
    text: str = Field(min_length=1, max_length=20000)
    client_id: str = Field(min_length=8, max_length=100)
    question_id: str = ""
    artifact_id: str = ""
    evidence_id: str = ""


def conversation_uses_ai(request: ChatRequest | str, workspace_state: str | None = None,
                         selected_artifact_kind: str | None = None) -> bool:
    """Pure routing guard; missing state is conservative for the freeze command."""
    text = (request.text if isinstance(request, ChatRequest) else request).strip()
    if text in {"현재 상태", "도움말", "어디까지 했어?", "이걸로 가자", "제출했다",
                "이건 Adjacent", "RAG 빼", "이건 내가 한 거 아님", "이 수치 틀림"}:
        return False
    if text.startswith("문항 추가:"):
        return False
    if text == "잠가":
        if selected_artifact_kind == "QuestionPortfolio" or (selected_artifact_kind or "").startswith("Resume"):
            return False
        # freeze() reruns cross-document AI QA; other locks/approvals don't.
        return workspace_state is None or workspace_state == "READY_TO_FREEZE"
    return True


class AnalysisFieldChange(Schema):
    field: Literal[
        "actual_outputs",
        "base_profession",
        "specialty",
        "tools",
        "main_skills",
        "differentiators",
        "output_importance",
        "hiring_context",
        "positioning",
        "base_profession_identity",
        "main_skill_message",
        "differentiator_message",
        "fatal_gaps",
        "selection_risks",
        "fatal_gap_strategy",
        "assignment_statement",
        "do_not_position_as",
        "question_portfolio",
    ]
    old_value: str | list[str] | list[OutputImportance]
    new_value: str | list[str] | list[OutputImportance]


class ChatPlan(Schema):
    reply: str
    action: Literal[
        "reply",
        "analyze",
        "research",
        "evidence-map",
        "strategy",
        "add-question",
        "question-brief",
        "claim-test",
        "generate",
        "review",
        "review-answers",
        "revise",
        "patch",
        "resume",
        "correct-evidence",
        "correct-analysis",
    ]
    question_text: str = ""
    character_limit: int = Field(default=1000, ge=1, le=20000)
    old_text: str = ""
    new_text: str = ""
    correction_kind: Literal["OWNERSHIP", "METRIC", "ADJACENT", "EXCLUDE_RAG"] = "OWNERSHIP"
    field_changes: list[AnalysisFieldChange] = []


def history(service: Workflow, workspace: str):
    service.ws(workspace)
    return [
        view(r)
        for r in service.db.scalars(
            select(Record)
            .where(Record.user_id == service.user, Record.kind == "ConversationTurn")
            .order_by(Record.created_at, Record.id)
        )
        if r.data["workspace_id"] == workspace
    ]


def planner_artifacts(items: list[Artifact], selected: Artifact | None):
    """Routing uses document identity/state; writing still loads full proof.

    Never send every previous draft to the intent classifier. Full selected
    content remains intact for exact edits/corrections; an oversized selected
    document is rejected by the provider preflight, never silently shortened.
    """
    latest: dict[tuple[str, str], Artifact] = {}
    for item in items:
        key = item.kind, item.slot
        if key not in latest or latest[key].version < item.version:
            latest[key] = item
    summaries = []
    for item in latest.values():
        summaries.append({
            "id": item.id, "version": item.version, "kind": item.kind,
            "slot": item.slot, "status": item.status,
            "selected": bool(selected and selected.id == item.id),
            "truth_role": "DERIVED_ARTIFACT_NOT_CANONICAL_FACT",
            "routing_summary_only": True,
            "content_available_in_action": True,
        })
    return summaries


def planner_history(past: list[dict]):
    # Message excerpts only help intent; no historical answer is proof/approval.
    values = []
    for turn in past[-4:]:
        data = turn["data"]
        request = data.get("request", {})
        response = data.get("response", {})
        values.append({"message_excerpt": str(request.get("text", ""))[:600],
                       "reply_excerpt": str(response.get("text", ""))[:600],
                       "status": response.get("status"), "not_fact_or_approval": True})
    return values


def converse(service: Workflow, workspace: str, request: ChatRequest):
    ws = service.ws(workspace)
    past = history(service, workspace)
    for turn in past:
        if turn["data"]["request"]["client_id"] == request.client_id:
            if turn["data"]["request"] != request.model_dump():
                raise ValueError("같은 메시지 번호에 다른 내용이 전달되었습니다.")
            return turn
    qid = request.question_id
    if qid:
        service.question(workspace, qid)
    artifact = None
    if request.artifact_id:
        artifact = service.db.scalar(
            select(Artifact).where(
                Artifact.id == request.artifact_id,
                Artifact.user_id == service.user,
                Artifact.workspace_id == workspace,
            )
        )
        if artifact is None:
            raise LookupError("이 지원 작업의 문서를 선택해 주세요.")
        if artifact.slot != qid:
            raise ValueError("선택한 문서와 문항이 다릅니다.")
    before = set(
        service.db.scalars(
            select(Artifact.id).where(Artifact.workspace_id == workspace, Artifact.user_id == service.user)
        )
    )
    response: dict = {"text": "", "artifact_ids": [], "status": "OK"}
    text = request.text.strip()
    try:
        with service.db.begin_nested():
            if text in {
                "ㄱㄱ",
                "이걸로 가자",
                "잠가",
                "제출했다",
                "다시",
                "이건 Adjacent",
                "RAG 빼",
                "이건 내가 한 거 아님",
                "이 수치 틀림",
                "전체 문서 검수",
            }:
                # A latest STALE document is a valid routing target for recovery.
                # The selected version must still be current, and each operation
                # enforces freshness/approval on the artifacts it actually uses.
                if artifact:
                    current = latest(service.db, service.user, workspace, artifact.kind, artifact.slot)
                    if current is None or current.id != artifact.id:
                        raise ValueError("이전 버전이 선택되어 있습니다. 현재 버전을 선택해 주세요.")
                if artifact and artifact.kind == "QuestionPortfolio" and text in {"이걸로 가자", "잠가"}:
                    from career.portfolio import approve

                    response["changes"] = {"patched": [approve(service, workspace).id]}
                else:
                    response["changes"] = service.command(
                        workspace,
                        text,
                        qid,
                        request.evidence_id,
                        resume=bool(artifact and artifact.kind.startswith("Resume")),
                    )
                response["text"] = "요청한 작업을 반영했습니다. 오른쪽 보관함에서 현재 버전을 확인하세요."
                for ident in response["changes"].get("patched_artifacts", []):
                    created = service.db.get(Artifact, ident)
                    if created and created.kind == "CompanyResearchResult":
                        response["text"] = created.data.get("scope", {}).get("summary", response["text"]) + " ‘회사 조사·채용 배경 확인’에서 자료를 보완하고 가설 또는 자료 부족을 확인해 주세요. 이후 ‘ㄱㄱ’로 직무 분석을 진행합니다."
            elif text in {"현재 상태", "도움말", "어디까지 했어?"}:
                response["text"] = (
                    f"{ws.company} · {ws.role} 지원을 준비하고 있습니다. 등록한 문항은 {len(ws.data.get('questions', []))}개입니다. 오른쪽에서 문항을 선택해 설계·작성·검수를 이어갈 수 있습니다. ‘ㄱㄱ’는 현재 단계의 다음 작업을 실행하고, ‘이걸로 가자’는 선택한 메시지 또는 전략을 승인합니다."
                )
            elif text.startswith("문항 추가:"):
                question = service.add_question(workspace, text.split(":", 1)[1].strip(), 1000)
                response.update(
                    text="문항을 보관함에 추가했습니다. 문항을 선택하면 작성 준비를 시작합니다.",
                    question_id=question["id"],
                )
            elif service.provider is None and not provider_available():
                response["text"] = (
                    "현재 AI가 연결되지 않아 자유로운 대화 분석은 사용할 수 없습니다. ‘문항 추가: 질문 내용’으로 문항을 저장하거나, 오른쪽 ‘직접 편집’에서 분석·본문을 입력할 수 있습니다. ‘현재 상태’로 진행 상황도 확인할 수 있어요."
                )
                response["status"] = "MANUAL_MODE"
            else:
                active = list(
                    service.db.scalars(
                        select(Artifact).where(
                            Artifact.workspace_id == workspace,
                            Artifact.user_id == service.user,
                        )
                    )
                )
                plan = ChatPlan.model_validate(
                    service.ai(
                        "conversation_router",
                        {
                            "task": "Answer or perform exactly ONE requested action. Do not invent progress. Approval, freeze, and submission are unavailable actions. Ask for missing information. Only patch when user explicitly requests a text edit; preserve untouched text. Use review-answers when the user supplies answers or dispositions to review questions; this records and verifies their own words, never invents answers or edits documents. Artifacts, not history, determine stage.",
                            "message": text,
                            "correction_policy": "Correct evidence ONLY if the user explicitly states a fact/ownership/metric is wrong or asks to change its mapping. correct-analysis proposes field_changes with exact old_value/new_value for the SELECTED OpportunityBrief or ApplicationBrief only when user asks to change role reality or positioning. Do not change company facts or JD. Proposal requires separate user approval. For ambiguity reply with a short question. Never infer approval or correction from ordinary discussion.",
                            "selected_evidence_id": request.evidence_id,
                            "selected_question_id": qid,
                            "selected_artifact": view(artifact) if artifact else None,
                            "workspace": {
                                "company": ws.company,
                                "role": ws.role,
                                "state": ws.state,
                                "questions": ws.data.get("questions", []),
                            },
                            "artifacts": planner_artifacts(active, artifact),
                            "context_selection": "Intent routing sees latest IDs/statuses only. Full selected document is intact. Subsequent action loads full approved artifacts, canonical facts and evidence. Never infer facts/approval from summaries or history.",
                            "recent_conversation": planner_history(past),
                        },
                        ChatPlan,
                    )
                )
                is_resume = bool(artifact and artifact.kind.startswith("Resume"))
                if plan.action == "review-answers":
                    if artifact is None or artifact.kind not in {"Review", "ResumeReview", "ReviewResponses", "ResumeReviewResponses", "Draft", "ResumeContent"}:
                        raise ValueError("답변할 문항의 현재 검수 또는 본문을 오른쪽 보관함에서 선택해 주세요.")
                    if service.artifact(workspace, artifact.kind, artifact.slot).id != artifact.id:
                        raise ValueError("이전 버전이 선택되어 있습니다. 현재 검수의 질문을 확인해 주세요.")
                if plan.action in {"patch", "revise"}:
                    if artifact is None or artifact.kind not in {"Draft", "ResumeContent"}:
                        raise ValueError("수정할 본문을 오른쪽 보관함에서 선택해 주세요.")
                    current = service.artifact(workspace, artifact.kind, artifact.slot)
                    if current.id != artifact.id:
                        raise ValueError("이전 버전이 선택되어 있습니다. 현재 버전을 선택해 주세요.")
                if plan.action == "patch" and not plan.old_text:
                    raise ValueError("수정할 원문 구간이 필요합니다.")
                if plan.action == "correct-evidence" and not request.evidence_id:
                    raise ValueError("정정할 경험을 입력창 아래에서 선택해 주세요.")
                operations = {
                    "analyze": lambda: service.analyze(workspace),
                    "research": lambda: service.research(workspace, live=True),
                    "evidence-map": lambda: service.map_evidence(workspace),
                    "strategy": lambda: service.strategy(workspace),
                    "add-question": lambda: service.add_question(
                        workspace, plan.question_text, plan.character_limit
                    ),
                    "question-brief": lambda: service.question_brief(workspace, qid),
                    "claim-test": lambda: service.test_claim(workspace, qid),
                    "generate": lambda: service.draft(workspace, qid),
                    "review": lambda: service.review(workspace, qid, resume=is_resume),
                    "revise": lambda: service.revise(workspace, qid, resume=is_resume),
                    "patch": lambda: service.patch_document(
                        workspace, qid, plan.old_text, plan.new_text, resume=is_resume
                    ),
                    "resume": lambda: service.resume(workspace),
                    "correct-evidence": lambda: service.command(
                        workspace,
                        {
                            "OWNERSHIP": "이건 내가 한 거 아님",
                            "METRIC": "이 수치 틀림",
                            "ADJACENT": "이건 Adjacent",
                            "EXCLUDE_RAG": "RAG 빼",
                        }[plan.correction_kind],
                        qid,
                        request.evidence_id,
                    ),
                }
                from career.review_resolution import from_message

                operations["review-answers"] = lambda: from_message(service, workspace, qid, text, is_resume)
                if plan.action == "reply":
                    response["text"] = plan.reply
                elif plan.action == "correct-analysis":
                    from career.structured_corrections import propose

                    if artifact is None:
                        raise ValueError("고칠 직무 분석 또는 지원 전략을 오른쪽에서 선택해 주세요.")
                    changes = [item.model_dump() for item in plan.field_changes]
                    if len({item["field"] for item in changes}) != len(changes):
                        raise ValueError("같은 분석 항목을 중복해서 고칠 수 없습니다.")
                    proposal = propose(
                        service,
                        workspace,
                        artifact.id,
                        {item["field"]: item["old_value"] for item in changes},
                        {item["field"]: item["new_value"] for item in changes},
                        request.text,
                    )
                    response.update(
                        text="직무 해석의 교정안을 만들었습니다. 수정 전후를 확인하고 반영해 주세요.",
                        proposal_id=proposal["id"],
                        status="WAITING_REVIEW",
                    )
                elif plan.action == "patch":
                    from career.human_review import propose_patch

                    assert artifact is not None
                    old = service.artifact(workspace, artifact.kind, qid)
                    preview = old.data["text"].replace(plan.old_text, plan.new_text, 1)
                    proposal = propose_patch(
                        service,
                        workspace,
                        qid,
                        {
                            "old_text": plan.old_text,
                            "new_text": plan.new_text,
                            "claims": [
                                {
                                    "text": preview,
                                    "type": "FACT",
                                    "evidence_ids": old.data["selected_evidence_ids"],
                                    "support": "NEEDS_REVIEW",
                                    "ownership_ok": False,
                                }
                            ],
                            "issue_codes": [],
                        },
                        resume=is_resume,
                    )
                    response.update(
                        text="수정 전후를 확인할 제안을 만들었습니다. 반영할 문장을 직접 고르고 승인해 주세요.",
                        proposal_id=proposal["id"],
                        status="WAITING_REVIEW",
                    )
                else:
                    result = operations[plan.action]()
                    response["text"] = "요청한 작업을 저장했습니다. 오른쪽 보관함에서 결과를 확인하세요."
                    if plan.action == "review-answers":
                        response.update(
                            text="답변을 기록하고 검증했습니다. " + (
                                "현재 검수 질문의 처리를 마쳤습니다. 문서를 읽고 최종 잠금을 선택해 주세요."
                                if result.data["status"] == "RESOLVED" else
                                "아직 답변이나 보완이 필요한 질문이 있습니다. 검수 답변 기록을 확인해 주세요."
                            ),
                            status="WAITING_REVIEW",
                        )
                    if plan.action == "revise":
                        response.update(
                            text="검수 의견에 따른 수정 제안을 만들었습니다. 수정 전후를 확인한 뒤 반영하거나 거절하세요.",
                            proposal_id=result["id"],
                            status="WAITING_REVIEW",
                        )
                    if plan.action == "add-question":
                        response["question_id"] = result["id"]
                response["context_notice"] = "대화 의도 판단에는 문서 ID·상태와 최근 대화 일부를 사용했습니다. 작성·검수는 원문 근거와 승인된 자료를 다시 읽습니다."
            service.db.flush()
    except (ValueError, LookupError, ProviderUnavailable) as exc:
        response.update(text=str(exc), status="NEEDS_INPUT")
    except Exception:
        response.update(
            text="연결 문제로 작업을 완료하지 못했습니다. 저장된 문서는 유지됩니다. 잠시 후 다시 시도해 주세요.",
            status="ERROR",
        )
    response["artifact_ids"] = [
        a.id
        for a in service.db.scalars(
            select(Artifact)
            .where(Artifact.workspace_id == workspace, Artifact.user_id == service.user)
            .order_by(Artifact.created_at, Artifact.id)
        )
        if a.id not in before
    ]
    record = Record(
        user_id=service.user,
        kind="ConversationTurn",
        data={"workspace_id": workspace, "request": request.model_dump(), "response": response},
    )
    service.db.add(record)
    service.db.flush()
    return view(record)
