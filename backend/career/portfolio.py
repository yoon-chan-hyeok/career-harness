"""A versioned plan for distinct question roles, messages and evidence candidates."""

from pydantic import Field

from career.artifacts import fresh, latest, lock, save
from career.schemas import Schema
from career.telemetry import feedback


class QuestionAllocation(Schema):
    question_id: str
    evaluation_intent: str
    identity_role: str
    primary_message_candidates: list[str] = Field(min_length=1, max_length=3)
    evidence_candidate_ids: list[str] = Field(min_length=1)
    avoided_repetition: list[str]


class QuestionPortfolio(Schema):
    items: list[QuestionAllocation]


def require_current(service, workspace, brief):
    from career.joint_portfolio import require_decision

    require_decision(service, workspace, portfolio=True)
    ws = service.ws(workspace)
    if len(ws.data.get("questions", [])) < 2:
        return
    portfolio = latest(service.db, service.user, workspace, "QuestionPortfolio", required=False)
    if portfolio is None or portfolio.status != "LOCKED":
        raise ValueError("여러 문항의 역할과 메시지 후보를 먼저 배분하고 승인해 주세요.")
    fresh(service.db, service.user, portfolio)
    if portfolio.id not in brief.depends_on:
        raise ValueError("현재 문항별 역할 배분을 반영해 메시지를 다시 설계해 주세요.")


def plan(service, workspace, manual=None, *, _joint_decision=None):
    ws = service.ws(workspace)
    service.editable(ws)
    if _joint_decision is None and latest(service.db, service.user, workspace, "MaterialDecision", required=False):
        raise ValueError("현재 소재 선택 화면에서 문항 배분을 수정해 주세요.")
    strategy = service.artifact(workspace, "ApplicationBrief")
    pack = service.artifact(workspace, "EvidencePack")
    questions = ws.data.get("questions", [])
    if not questions:
        raise ValueError("먼저 지원 문항을 등록해 주세요.")
    value = QuestionPortfolio.model_validate(
        manual
        or service.ai(
            "question_portfolio",
            {
                "task": "Allocate every supplied question exactly once. Give each a distinct identity_role, evaluation_intent and 1-3 primary message candidates with actual evidence candidates. Reusing a project is allowed; repeated fact, metric, conclusion and message are not. Cover the base profession, main work, collaboration, values and specialty only where questions and evidence support them. Do not invent missing experiences.",
                "questions": questions,
                "strategy": strategy.data,
                "evidence_pack": pack.data,
            },
            QuestionPortfolio,
        )
    ).model_dump()
    if {item["question_id"] for item in value["items"]} != {q["id"] for q in questions} or len(
        value["items"]
    ) != len(questions):
        raise ValueError("현재 등록한 모든 문항을 한 번씩 배분해 주세요.")
    allowed = {i["evidence_id"] for i in pack.data["items"] if i["classification"] != "NO_EVIDENCE"}
    messages, roles = set(), set()
    for item in value["items"]:
        if not set(item["evidence_candidate_ids"]) <= allowed:
            raise ValueError("문항 역할에는 현재 확인된 근거 후보만 연결해 주세요.")
        if (
            not item["identity_role"].strip()
            or not item["evaluation_intent"].strip()
            or item["identity_role"] in roles
        ):
            raise ValueError("문항마다 구별되는 역할과 평가 의도를 지정해 주세요.")
        roles.add(item["identity_role"])
        for message in item["primary_message_candidates"]:
            if not message.strip() or message.strip() in messages:
                raise ValueError("문항의 핵심 메시지 후보가 중복됩니다.")
            messages.add(message.strip())
    result, _ = save(
        service.db,
        service.user,
        workspace,
        "QuestionPortfolio",
        value,
        deps=[strategy.id, pack.id] + ([_joint_decision.id] if _joint_decision else []),
        sources=service.reference_sources("question_portfolio"),
        model="manual" if manual else service.current_model,
    )
    return result


def approve(service, workspace):
    from career.joint_portfolio import require_decision

    service.editable(service.ws(workspace))
    decision = require_decision(service, workspace)
    result = service.artifact(workspace, "QuestionPortfolio")
    if decision and decision.id not in result.depends_on:
        raise ValueError("현재 소재 선택을 반영해 문항 배분을 다시 구성해 주세요.")
    lock(service.db, service.user, result)
    feedback(service.db, service.user, result, "ACCEPT")
    return result
