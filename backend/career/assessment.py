"""Job-side metadata and candidate-side assessments stay separate."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select

from career.artifacts import latest, lock, save, stale
from career.db import Record
from career.models import Artifact, Workspace
from career.schemas import OpportunityAssessment
from career.truth import canonical


def validate_opportunity(data, source_ids):
    outputs = data["actual_outputs"]
    importance = data.get("output_importance", [])
    if any(i["output"] not in outputs for i in importance) or len({i["output"] for i in importance}) != len(
        importance
    ):
        raise ValueError("업무 중요도는 현재 공고의 산출물에 한 번씩 지정해 주세요.")
    if any(
        r["source_id"] not in source_ids | {"jd"}
        for r in data.get("required", []) + data.get("preferred", [])
    ):
        raise ValueError("지원 조건은 공고 또는 등록된 조사 출처와 연결해 주세요.")
    if data.get("posting_source", "jd") not in source_ids | {"jd"}:
        raise ValueError("채용 상태의 확인 출처를 연결해 주세요.")
    if data.get("deadline_at"):
        try:
            deadline = datetime.fromisoformat(data["deadline_at"])
            timezone = ZoneInfo(data["deadline_timezone"])
            if deadline.tzinfo is None or deadline.utcoffset() != deadline.astimezone(timezone).utcoffset():
                raise ValueError("마감 시각과 시간대가 일치하지 않습니다.")
        except (ZoneInfoNotFoundError, KeyError, ValueError) as exc:
            raise ValueError("마감은 정확한 시간과 유효한 시간대를 함께 입력해 주세요.") from exc


def assess(service, ident, manual=None):
    service.editable(service.ws(ident))
    opportunity = service.artifact(ident, "OpportunityBrief")
    pack = service.artifact(ident, "EvidencePack")
    profile = canonical(service.db, service.user)
    data = OpportunityAssessment.model_validate(
        manual
        or service.ai(
            "opportunity_assessment",
            {
                "opportunity": opportunity.data,
                "evidence_pack": pack.data,
                "canonical_profile": profile,
                "task": "Check ALL Required eligibility first. Unknown stays NEEDS_VERIFICATION. Separate Fit/Career Value/Action Priority. Never invent salary/reputation; deadline affects action order only. Recommend; human decides.",
            },
            OpportunityAssessment,
        )
    ).model_dump()
    required = {r["requirement"] for r in opportunity.data.get("required", [])}
    checks = {r["requirement"] for r in data["eligibility"]}
    if required != checks or len(checks) != len(data["eligibility"]):
        raise ValueError("공고의 모든 필수 조건을 빠짐없이 한 번씩 확인해 주세요.")
    for check in data["eligibility"]:
        if not set(check["profile_keys"]) <= set(profile):
            raise ValueError("현재 확인된 프로필만 자격 근거로 사용할 수 있습니다.")
        if check["status"] == "MET" and not check["profile_keys"]:
            raise ValueError("충족 판정에는 확인된 프로필 근거가 필요합니다.")
    research = latest(service.db, service.user, ident, "CompanyResearchResult", required=False)
    source_ids = {s["id"] for s in research.data.get("sources", [])} if research else set()
    allowed = source_ids | {"jd"} | {f["source_id"] for f in profile.values()}
    for axis in ("fit", "career_value", "action_priority"):
        if not set(data[axis]["source_ids"]) <= allowed:
            raise ValueError("평가 출처는 현재 공고·조사·확인된 프로필에 연결해 주세요.")
    if data["career_value"]["level"] != "UNKNOWN" and not (
        set(data["career_value"]["source_ids"]) & (source_ids | {"jd"})
    ):
        raise ValueError("커리어 가치 근거가 없으면 확인 필요로 남겨 주세요.")
    deadline = opportunity.data.get("deadline_at", "")
    expired = bool(deadline and datetime.fromisoformat(deadline) <= datetime.now().astimezone())
    if (
        opportunity.data.get("posting_status") == "CLOSED"
        or expired
        or any(c["status"] == "NOT_MET" for c in data["eligibility"])
    ):
        data["recommendation"] = "SKIP"
    elif (
        any(c["status"] == "NEEDS_VERIFICATION" for c in data["eligibility"])
        or opportunity.data.get("posting_status") != "OPEN"
    ):
        if data["recommendation"] in {"PROCEED", "PROCEED_WITH_GAP"}:
            data["recommendation"] = "LOW_PRIORITY"
    critical = {
        o["output"] for o in opportunity.data.get("output_importance", []) if o["importance"] == "CRITICAL"
    }
    data["critical_gaps"] = sorted(critical & set(pack.data["uncovered_outputs"]))
    if data["critical_gaps"] and data["recommendation"] == "PROCEED":
        data["recommendation"] = "PROCEED_WITH_GAP"
    if data["critical_gaps"] and data["fit"]["level"] == "HIGH":
        data["fit"] = {
            **data["fit"],
            "level": "MEDIUM",
            "reason": data["fit"]["reason"] + " · 필수 핵심 업무의 직접 근거가 없어 적합도를 제한했습니다.",
        }
    data["human_decision"] = "PENDING"
    item, _ = save(
        service.db,
        service.user,
        ident,
        "OpportunityAssessment",
        data,
        deps=[opportunity.id, pack.id],
        sources=list(
            set(service.reference_sources("opportunity_assessment"))
            | {f["source_id"] for f in profile.values()}
        ),
        model="manual" if manual else service.current_model,
    )
    return item


def decide(service, ident, artifact_id, decision):
    service.editable(service.ws(ident))
    item = service.artifact(ident, "OpportunityAssessment")
    if item.id != artifact_id or decision not in {"PROCEED", "HOLD", "SKIP"}:
        raise ValueError("현재 평가 버전과 지원·보류·건너뛰기 중 하나를 확인해 주세요.")
    record = Record(
        user_id=service.user,
        kind="HumanDecision",
        data={
            "workspace_id": ident,
            "artifact_id": item.id,
            "version": item.version,
            "decision": decision,
        },
    )
    service.db.add(record)
    lock(service.db, service.user, item)
    ws = service.ws(ident)
    if ws.data.get("opportunity_decision") != {"artifact_id": item.id, "decision": decision}:
        stale(service.db, service.user, [item.id])
    ws.data = {**ws.data, "opportunity_decision": {"artifact_id": item.id, "decision": decision}}
    # Record is authoritative; proposal content is retained verbatim.
    service.db.flush()
    return {"id": record.id, **record.data}


def current_deadline_status(opportunity, instant=None):
    if opportunity is None:
        return "UNKNOWN"
    if opportunity.data.get("posting_status") == "CLOSED":
        return "CLOSED"
    deadline = opportunity.data.get("deadline_at")
    if deadline:
        try:
            parsed = datetime.fromisoformat(deadline)
            if parsed.tzinfo is None:
                return "UNKNOWN"
            if parsed <= (instant or datetime.now(UTC)):
                return "EXPIRED"
        except (ValueError, TypeError):
            return "UNKNOWN"
    return "OPEN" if opportunity.data.get("posting_status") == "OPEN" else "UNKNOWN"


def rankings(db, user):
    assessments = {}
    for a in db.scalars(
        select(Artifact)
        .where(Artifact.user_id == user, Artifact.kind == "OpportunityAssessment")
        .order_by(Artifact.version)
    ):
        assessments[a.workspace_id] = a
    rows = []
    for ws in db.scalars(select(Workspace).where(Workspace.user_id == user)):
        a = assessments.get(ws.id)
        if (
            a is None
            or a.status not in {"ACTIVE", "LOCKED"}
            or ws.state in {"SUBMITTED", "CLOSED", "SUBMISSION_FROZEN"}
        ):
            continue
        opportunity = latest(db, user, ws.id, "OpportunityBrief", required=False)
        deadline_status = current_deadline_status(opportunity)
        next_action = {
            "NEED_USER_ACTION": "변경된 근거와 문서 다시 검토",
            "WAITING_STRATEGY_APPROVAL": "지원 전략 승인",
            "WAITING_QUESTION_APPROVAL": "문항 메시지 승인",
            "REVIEWING": "작성 문서 검수·잠금",
            "READY_TO_FREEZE": "제출 전 문서 확인",
        }.get(ws.state, "지원 작업 이어가기")
        rows.append(
            {
                "workspace_id": ws.id,
                "company": ws.company,
                "role": ws.role,
                "fit": a.data["fit"]["level"],
                "career_value": a.data["career_value"]["level"],
                "action_priority": a.data["action_priority"]["level"],
                "recommendation": a.data["recommendation"],
                "current_deadline_status": deadline_status,
                "next_action": "마감 경과 · 공고 다시 확인" if deadline_status in {"EXPIRED", "CLOSED"} else next_action,
                "deadline_at": opportunity.data.get("deadline_at", "") if opportunity else "",
                "decision": (
                    ws.data.get("opportunity_decision", {}).get("decision", "PENDING")
                    if ws.data.get("opportunity_decision", {}).get("artifact_id") == a.id
                    else "PENDING"
                ),
            }
        )
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "UNKNOWN": 3}

    def deadline_order(row):
        try:
            return datetime.fromisoformat(row["deadline_at"]).timestamp() if row["deadline_at"] else float("inf")
        except (ValueError, TypeError):
            return float("inf")

    return {
        "fit_order": sorted(rows, key=lambda r: (order[r["fit"]], order[r["career_value"]], r["company"])),
        "action_order": sorted(
            rows,
            key=lambda r: (
                r["current_deadline_status"] in {"EXPIRED", "CLOSED"},
                r["recommendation"] == "SKIP" or r["decision"] == "SKIP",
                order[r["action_priority"]],
                deadline_order(r),
                r["company"],
            ),
        ),
    }
