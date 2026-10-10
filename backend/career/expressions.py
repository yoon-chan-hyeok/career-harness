"""Approved personal expression preferences are not a new source of facts."""

from copy import deepcopy
from hashlib import sha256
from typing import Literal

from pydantic import Field, StrictBool
from sqlalchemy import func, select

from career.artifacts import fresh, latest, save
from career.db import now
from career.models import Artifact
from career.schemas import Schema
from career.truth import owned, view
from career.validation import hard_qa, ledger_coverage

KIND = "ApprovedExpression"
PATTERNS = {
    "JUDGMENT_FIRST": {"label": "판단을 먼저", "text": "[판단]이 필요하다고 보았습니다. [관찰 근거]를 확인하고 [내 행동]을 선택했습니다."},
    "CONSTRAINT_CHOICE": {"label": "제약에서 선택으로", "text": "[제약]이 있는 상황에서 [대안]을 비교했습니다. [선택 기준]에 따라 [내 행동]을 진행했습니다."},
    "OBSERVATION_REFRAME": {"label": "관찰에서 문제 재정의로", "text": "[관찰]을 통해 [기존 가정]을 다시 살폈습니다. 문제를 [재정의]하고 [내 행동]으로 연결했습니다."},
    "OUTPUT_ACTION": {"label": "산출물 뒤에 행동", "text": "[확인된 산출물]을 만들었습니다. 이를 위해 [내 행동]을 수행하고 [검증 방법]으로 확인했습니다."},
    "VALUE_BOUNDARY": {"label": "업무 가치와 한계", "text": "[내 행동]으로 [가능해진 업무]를 제시했습니다. 확인한 범위는 [검증 범위]이며 [미검증 한계]는 남아 있습니다."},
    "LEARNING_TRANSFER": {"label": "배운 판단을 업무로", "text": "이 경험에서 [배운 판단 기준]을 정리했습니다. [지원 직무의 업무]에서도 [적용할 행동]에 활용하고자 합니다."},
}
Logic = Literal["상황", "제약", "관찰", "판단", "대안", "행동", "산출물", "검증", "업무 가치", "한계", "배운 점", "직무 연결"]
Tone = Literal["짧은 문장", "담백함", "설명 중심", "판단 먼저", "산출물 먼저"]


class Approval(Schema):
    document_id: str
    excerpt: str = Field(min_length=4, max_length=2000)
    pattern_ids: list[str] = Field(min_length=1, max_length=3)
    logic_pattern: list[Logic] = Field(min_length=2, max_length=12)
    tone_tags: list[Tone] = Field(min_length=1, max_length=3)
    scope: Literal["DOMAIN", "QUESTION_TYPE", "PROJECT"] = "QUESTION_TYPE"
    evidence_id: str | None = None
    allow_grounded_excerpt: StrictBool = False
    confirmed: StrictBool = False


def catalogue():
    return [{"id": key, **value} for key, value in PATTERNS.items()]


def approve(service, workspace: str, payload: dict):
    entry = Approval.model_validate(payload)
    service.ws(workspace)
    document = owned(service.db, Artifact, service.user, entry.document_id)
    if document.workspace_id != workspace or document.kind not in {"Draft", "ResumeContent"}:
        raise ValueError("이 지원 작업의 자소서 또는 이력서를 선택해 주세요.")
    current = service.artifact(workspace, document.kind, document.slot)
    if current.id != document.id or document.status != "LOCKED":
        raise ValueError("현재 최종 잠금한 문서에서 저장할 표현을 선택해 주세요.")
    if entry.confirmed is not True:
        raise ValueError("원문과 재사용할 표현 구조를 읽고 직접 승인해 주세요.")
    excerpt = entry.excerpt.strip()
    if len(excerpt) < 4 or document.data["text"].count(excerpt) != 1:
        raise ValueError("현재 문서에서 정확히 한 곳에 있는 원문 구절을 선택해 주세요.")
    if not set(entry.pattern_ids) <= PATTERNS.keys() or len(set(entry.pattern_ids)) != len(entry.pattern_ids):
        raise ValueError("제공된 표현 구조에서 중복 없이 선택해 주세요.")
    if len(set(entry.logic_pattern)) != len(entry.logic_pattern) or len(set(entry.tone_tags)) != len(entry.tone_tags):
        raise ValueError("논리 순서와 말투는 중복 없이 선택해 주세요.")
    if entry.scope == "PROJECT":
        if not entry.evidence_id or entry.evidence_id not in document.data.get("selected_evidence_ids", []):
            raise ValueError("이 문서에서 사용한 프로젝트 근거를 선택해 주세요.")
        service.selected([entry.evidence_id])
    elif entry.evidence_id:
        raise ValueError("프로젝트 범위를 선택한 경우에만 근거를 지정해 주세요.")
    domain = "RESUME" if document.kind == "ResumeContent" else "COVER"
    question_type = "RESUME" if domain == "RESUME" else service.artifact(workspace, "QuestionBrief", document.slot).data["question_type"]
    slot = document.id + ":" + sha256(excerpt.encode()).hexdigest()[:24]
    previous = latest(service.db, service.user, workspace, KIND, slot, required=False)
    data = {**entry.model_dump(exclude={"confirmed"}), "excerpt": excerpt,
        "domain": domain, "question_type": question_type, "document_version": document.version,
        "question_prompt": "" if domain == "RESUME" else service.question(workspace, document.slot)["text"],
        "authority": "EXPRESSION_ONLY", "active": True, "confirmed_at": now().isoformat()}
    if previous and previous.status == "LOCKED" and all(previous.data.get(key) == value for key, value in data.items() if key != "confirmed_at"):
        return previous
    count = service.db.scalar(select(func.count()).select_from(Artifact).where(
        Artifact.user_id == service.user, Artifact.kind == KIND)) or 0
    if count >= 500:
        raise ValueError("표현 기록이 500개에 도달했습니다. 필요한 표현만 남기도록 보관 자료를 정리해 주세요.")
    # Provenance is recorded, but expressions are not dependencies of their
    # source documents: otherwise revising that document creates a stale cycle.
    result, _ = save(service.db, service.user, workspace, KIND, data, slot=slot)
    result.status = "LOCKED"
    return result


def set_active(service, expression_id: str, active: bool):
    if type(active) is not bool:
        raise ValueError("표현 사용 여부를 선택해 주세요.")
    item = owned(service.db, Artifact, service.user, expression_id)
    if item.kind != KIND:
        raise LookupError("표현 기록을 찾을 수 없습니다.")
    service.ws(item.workspace_id)
    current = latest(service.db, service.user, item.workspace_id, KIND, item.slot)
    if current is None or current.id != item.id:
        raise ValueError("현재 표현 버전에서 사용 여부를 바꿔 주세요.")
    if item.data["active"] == active:
        return item
    result, _ = save(service.db, service.user, item.workspace_id, KIND,
        {**item.data, "active": active, "confirmed_at": now().isoformat()}, slot=item.slot)
    result.status = "LOCKED"
    return result


def _entries(service):
    return list(service.db.scalars(select(Artifact).where(Artifact.user_id == service.user,
        Artifact.kind == KIND, Artifact.status == "LOCKED").order_by(Artifact.created_at.desc(), Artifact.id).limit(500)))


def listing(service):
    return {"patterns": catalogue(), "expressions": [view(item) for item in _entries(service)]}


def _current_excerpt(service, item, selected):
    if not item.data.get("allow_grounded_excerpt"):
        return None
    try:
        document = owned(service.db, Artifact, service.user, item.data["document_id"])
        fresh(service.db, service.user, document)
        if document.status != "LOCKED":
            return None
        excerpt = item.data["excerpt"]
        claims = [deepcopy(claim) for claim in document.data["claims"] if claim["text"] in excerpt]
        if not claims or any(claim.get("profile_fact_ids") or claim.get("company_source_ids")
                or claim["support"] != "SUPPORTED" or not claim["ownership_ok"] for claim in claims):
            return None
        candidate = {"text": excerpt, "claims": claims}
        # Numbers, ownership and boundaries are checked against the currently
        # selected evidence, never against the expression record itself.
        service.validate_ledger(candidate, selected)
        if ledger_coverage(candidate) or hard_qa(excerpt, selected):
            return None
        return candidate
    except (LookupError, ValueError):
        return None


def context(service, domain: str, question_type: str, selected: list[dict], limit=3, *, question=""):
    selected_ids = {item["id"] for item in selected}
    matches = []
    for item in _entries(service):
        data = item.data
        if not data.get("active") or data["domain"] != domain:
            continue
        if data["scope"] == "PROJECT" and data["evidence_id"] not in selected_ids:
            continue
        if data["scope"] == "QUESTION_TYPE" and data["question_type"] != question_type and not (
            not question_type and question and data.get("question_prompt") == question
        ):
            continue
        if not set(data["pattern_ids"]) <= PATTERNS.keys():
            continue
        projected = {"expression_id": item.id, "version": item.version, "authority": "STYLE_ONLY",
            "logic_pattern": data["logic_pattern"], "tone": data["tone_tags"],
            "preferred_patterns": [PATTERNS[key]["text"] for key in data["pattern_ids"]],
            "avoid_patterns": ["과거 수치·이름·기여 범위 복사", "미확인 성과 확정"],
            "instruction": "빈칸은 현재 승인한 근거로만 채운다. 문항에 맞지 않는 구조는 생략한다."}
        excerpt = _current_excerpt(service, item, selected)
        if excerpt:
            projected["current_evidence_excerpt"] = excerpt
            projected["excerpt_authority"] = "RECHECKED_CURRENT_SELECTED_EVIDENCE_ONLY"
        matches.append((0 if data["scope"] == "PROJECT" else 1 if data["scope"] == "QUESTION_TYPE" else 2, projected))
    return [item for _, item in sorted(matches, key=lambda pair: pair[0])[:limit]]


def usage(projections: list[dict]):
    return [{"expression_id": item["expression_id"], "version": item["version"],
             "original_excerpt_rechecked": "current_evidence_excerpt" in item} for item in projections]
