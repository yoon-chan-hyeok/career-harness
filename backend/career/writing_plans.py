"""Per-question teaching guides and versioned, evidence-bound writing preparation."""

import hashlib
import json
import re
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from career.artifacts import fresh, latest, lock, save
from career.experience_options import evidence_fingerprint
from career.guide_publication import publishable_guide
from career.models import Artifact, Evidence
from career.truth import owned, register_source, view

if TYPE_CHECKING:
    from career.workflow import Workflow

VERSION = "writing-plan-v1"
RULES = [
    "현재 문항의 명시 요구와 글자 수 제한을 우선한다. 배분은 권고이며 고정 문단 수가 아니다.",
    "예시는 전개 방식의 참고다. 예시의 프로젝트·기관·수치를 지원자의 사실로 사용하지 않는다.",
    "개인 행동·성과는 선택한 현재 확인 근거에서만 쓴다. 부족한 사실은 묻거나 생략한다.",
    "강조 방향과 작성 메모는 새 사실이나 전략 승인으로 취급하지 않는다.",
    "질문에 직접 답하고, 상황 설명보다 본인의 판단·행동·검증을 구체적으로 남긴다.",
]
TEMPLATES = {
    "JOB_COMPETENCY": (
        "전문역량", "기술 이름보다 실제 문제에서 내린 판단·행동·검증으로 역량을 설명합니다.",
        ["역량을 한 문장으로", "문제와 본인 역할", "판단·행동·검증", "확인된 결과와 직무 연결"],
        ["반복해서 발휘한 본인의 수행 방식을 제시하세요.", "왜 해결해야 했는지와 본인이 맡은 범위를 적으세요.",
         "무엇을 관찰하고 왜 그 방법을 택했는지, 직접 한 일과 검증을 연결하세요.",
         "확인된 결과·한계와 지원 업무에서 활용할 범위를 적으세요."], [15, 20, 45, 20],
    ),
    "MOTIVATION": (
        "지원동기", "경험에서 생긴 선택 기준을 실제 직무·회사 근거와 연결합니다.",
        ["지원 이유와 선택 기준", "기준이 생긴 실제 경험", "왜 이 직무·회사인가", "기여 범위와 성장 방향"],
        ["이 일을 선택한 이유에 먼저 답하세요.", "선택 기준이 생긴 경험과 판단을 보여주세요.",
         "확인한 회사·직무의 구체적인 업무와 연결하세요.", "지금 할 수 있는 일과 배워야 할 부분을 구분하세요."],
        [20, 25, 35, 20],
    ),
    "COLLABORATION": (
        "협업·갈등", "팀의 결과와 본인의 조율·협력 행동을 구분해 보여줍니다.",
        ["공동 목표와 의견 차이", "본인의 역할·판단", "조율·협력한 구체적 행동", "결과와 배운 점"],
        ["누구와 어떤 목표를 맞춰야 했는지 설명하세요.", "의견이 달랐던 이유와 본인 책임을 적으세요.",
         "상대의 기준을 어떻게 확인하고 합의를 만들었는지 실제 행동을 적으세요.",
         "확인된 변화와 다음 협업에 적용할 점을 적으세요."], [20, 20, 40, 20],
    ),
    "CHALLENGE": (
        "도전·실패", "어려움 속에서 어떤 판단을 바꾸고 무엇을 실행했는지 보여줍니다.",
        ["목표와 어려움", "기존 접근과 판단의 전환", "실행·검증·보완", "결과·한계와 배운 점"],
        ["무엇을 달성하려 했고 어떤 제약이 있었는지 적으세요.", "어떤 관찰 때문에 방법을 바꿨는지 설명하세요.",
         "직접 시도하고 확인하며 보완한 과정을 적으세요.", "성공 여부를 꾸미지 않고 결과와 배운 점을 적으세요."],
        [20, 25, 35, 20],
    ),
    "STRENGTH_WEAKNESS": (
        "강점·약점", "실제 행동으로 드러난 특성과 보완 노력을 직무에 연결합니다.",
        ["질문에 대한 답", "특성이 드러난 경험", "활용 또는 보완 행동", "직무에서의 적용"],
        ["요구한 강점·약점을 빠짐없이 답하세요.", "자기평가보다 실제 행동 장면을 적으세요.",
         "강점을 발휘하거나 약점을 보완한 구체적인 행동을 적으세요.", "앞으로의 의도와 이미 확인된 결과를 구분하세요."],
        [15, 30, 35, 20],
    ),
    "VALUES": (
        "가치관", "선언보다 선택의 기준과 실제 행동으로 가치관을 보여줍니다.",
        ["중요하게 여기는 기준", "기준이 필요했던 상황", "기준에 따른 선택·행동", "결과와 일하는 방식"],
        ["질문이 요구한 가치나 원칙을 직접 답하세요.", "선택의 어려움과 본인 역할을 설명하세요.",
         "어떤 대안을 두고 왜 그 행동을 택했는지 적으세요.", "실제 결과와 이후 행동의 변화를 연결하세요."],
        [15, 25, 40, 20],
    ),
    "OTHER": (
        "문항 맞춤 구성", "질문에 명시된 요구에 직접 답하고 실제 근거로 설명합니다.",
        ["핵심 답변", "필요한 맥락", "본인의 판단·행동과 근거", "결과·배운 점·직무 연결"],
        ["질문에서 요구하는 답을 먼저 적으세요.", "답을 이해하는 데 필요한 상황만 남기세요.",
         "본인이 한 일과 그 판단을 뒷받침하는 원자료를 연결하세요.", "질문이 요구하는 범위에서 마무리하세요."],
        [15, 20, 45, 20],
    ),
}


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    emphasis_state: Literal["active", "unused", "discarded"] = "unused"
    emphasis: str = Field(default="", max_length=400)
    working_notes: str = Field(default="", max_length=4000)


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


@lru_cache(maxsize=1)
def catalog() -> tuple[dict, ...]:
    folder = Path(__file__).parent / "assets/writing_guides"
    return tuple(json.loads(path.read_text("utf-8")) for path in sorted(folder.glob("*.json")))


def family(text: str) -> str:
    for kind, pattern in [
        ("STRENGTH_WEAKNESS", r"장단점|강점.{0,10}약점|단점|약점"),
        ("COLLABORATION", r"협업|협력|갈등|소통|팀워크"),
        ("CHALLENGE", r"도전|실패|극복|어려움"),
        ("MOTIVATION", r"지원.?동기|입사.?후|왜.{0,8}회사"),
        ("VALUES", r"가치관|신념|성장.?과정|원칙"),
        ("JOB_COMPETENCY", r"역량|전문성|전문.?능력|직무|기술"),
    ]:
        if re.search(pattern, text):
            return kind
    return "OTHER"


def normal(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


def guide_for(company: str, role: str, question: dict) -> dict:
    for entry in catalog():
        meta = entry["selection_metadata"]
        if (normal(company) == normal(meta["source_company"])
                and normal(role) == normal(meta["source_role_name"])
                and normal(question["text"]) == normal(meta["original_prompt"])
                and question["limit"] == meta["length"]["maximum_characters"]):
            guide = deepcopy(entry["guide"])
            guide.update(origin="ARCHIVED_REFERENCE", label="원문 권장 구성",
                         source_verified_live=False, skill_rules=entry["rules"])
            return guide
    kind = family(question["text"])
    title, intent, labels, instructions, weights = TEMPLATES[kind]
    counts = [question["limit"] * weight // 100 for weight in weights]
    counts[-1] += question["limit"] - sum(counts)
    return {
        "guide_id": f"{VERSION}:{kind}:{question['limit']}",
        "origin": "SUGGESTED_STRUCTURE", "label": "문항 분석에 따른 제안 구성",
        "question": question["text"], "question_type": kind, "question_intent": intent,
        "length": {"maximum_characters": question["limit"], "counting_basis": "공백·줄바꿈 포함"},
        "allocation": [{"order": i + 1, "content": label, "approximate_characters": count,
                        "what_to_write": instruction}
                       for i, (label, count, instruction) in enumerate(zip(labels, counts, instructions, strict=True))],
        "writing_strategy": [{"instruction": item} for item in instructions],
        "reference_example": {
            "origin": "STRUCTURE_TEMPLATE_NOT_ACTUAL_APPLICATION",
            "use_as_applicant_fact": False,
            "paragraphs": [{"kind": "body", "function": label,
                            "text": f"[{label}] {instruction} 실제 경험의 근거로 이 부분을 채웁니다."}
                           for label, instruction in zip(labels, instructions, strict=True)],
        },
        "source": None, "fixed_body_paragraph_count": False, "skill_rules": RULES,
        "title": title,
    }


def preview(service: "Workflow", workspace: str, qid: str) -> dict:
    ws = service.ws(workspace)
    question = service.question(workspace, qid)
    guide = publishable_guide(guide_for(ws.company, ws.role, question))
    from career.guide_choices import enabled, resolve

    guide, choice, guide_deps = resolve(service, workspace, qid, guide)
    hold_notice = choice.get("notice") if choice else None
    try:
        execution_ready_guide(guide)
    except ValueError as error:
        hold_notice = str(error)
    guide_hash = digest(guide)
    strategy = latest(service.db, service.user, workspace, "ApplicationBrief", required=False)
    pack = latest(service.db, service.user, workspace, "EvidencePack", required=False)
    selection = latest(service.db, service.user, workspace, "ExperienceSelection", qid, required=False)
    if selection is None:
        selection = latest(service.db, service.user, workspace, "ExperienceSelection", "strategy", required=False)
    ids = sorted({i["evidence_id"] for i in (pack.data["items"] if pack else [])
                  if i["classification"] != "NO_EVIDENCE"})
    states, usable, sources = [], [], []
    for ident in ids:
        item = owned(service.db, Evidence, service.user, ident)
        states.append(evidence_fingerprint(item))
        try:
            data = service.selected([ident])[0]
            usable.append({"id": ident, "title": item.title})
            sources.extend(data["context_source_ids"])
            sources.append(item.source_id)
        except ValueError:
            continue
    valid_ids = {item["id"] for item in usable}
    chosen = (selection.data["evidence_id"]
              if selection and selection.status in {"ACTIVE", "LOCKED"}
              and selection.data["evidence_id"] in valid_ids else None)
    brief = latest(service.db, service.user, workspace, "QuestionBrief", qid, required=False)
    selected = [item for item in usable if item["id"] == chosen]
    if not selected and brief and brief.status in {"ACTIVE", "LOCKED"}:
        selected = [item for item in usable if item["id"] in brief.data["evidence_ids"]]
    revision = digest({"question": question, "company": ws.company, "role": ws.role,
                       "guide_hash": guide_hash, "evidence": states,
                       "strategy": [strategy.id, strategy.version, strategy.status] if strategy else None,
                       "pack": [pack.id, pack.version, pack.status] if pack else None,
                       "selection": [selection.id, selection.status] if selection else None})
    if choice:
        revision = digest([revision, choice])
    stored = latest(service.db, service.user, workspace, "WritingPlan", qid, required=False)
    is_current = bool(stored and stored.status in {"ACTIVE", "LOCKED"}
                      and stored.data["input_revision"] == revision)
    if is_current and stored is not None:
        try:
            fresh(service.db, service.user, stored)
        except ValueError:
            is_current = False
    emphasis = deepcopy(stored.data["emphasis"]) if stored else {"state": "unused", "text": ""}
    notes = stored.data.get("working_notes", "") if stored else ""
    missing = [] if selected else ["이 문항에 사용할 확인된 경험을 선택해 주세요."]
    if not strategy or strategy.status != "LOCKED":
        missing.append("지원 전략을 확인하고 승인해 주세요.")
    if brief and brief.status in {"ACTIVE", "LOCKED"}:
        for key, label in (("decision", "판단을 내린 이유"), ("insight", "배운 점"),
                           ("job_relevance", "지원 직무와의 연결")):
            if not brief.data.get(key):
                missing.append(f"{label}을 경험 원문에서 확인하고 문항 설계에 보완해 주세요.")
    draft = latest(service.db, service.user, workspace, "Draft", qid, required=False)
    review = latest(service.db, service.user, workspace, "Review", qid, required=False)
    phase = ("COMPLETED" if draft and draft.status == "LOCKED" else
             "REVIEW" if draft and draft.status == "ACTIVE" else
             "READY" if brief and brief.status == "LOCKED" else
             "MESSAGE" if brief and brief.status == "ACTIVE" else "PLANNING")
    return {
        "workspace_id": workspace, "question_id": qid, "question": question,
        "company": ws.company, "role": ws.role, "guide": guide,
        "guide_snapshot_sha256": guide_hash, "state_revision": revision,
        "plan": view(stored) if stored else None, "plan_current": is_current,
        "emphasis": emphasis, "working_notes": notes, "selected_evidence": selected,
        "missing_information": missing, "phase": phase,
        "review_current": bool(review and review.status in {"ACTIVE", "LOCKED"}),
        "counting_notice": "현재 서비스는 공백·줄바꿈을 포함한 글자 수로 검사합니다. 지원처가 바이트 등 다른 기준이면 별도 확인하세요.",
        "can_design": bool(strategy and strategy.status == "LOCKED" and usable and not hold_notice),
        "writing_hold_notice": hold_notice,
        "guide_selection_enabled": enabled(), "guide_choice": choice,
        "_guide_deps": guide_deps,
        "_source_ids": sorted(set(sources)), "_evidence_ids": ids,
    }


def public_preview(service: "Workflow", workspace: str, qid: str) -> dict:
    return {key: value for key, value in preview(service, workspace, qid).items()
            if not key.startswith("_")}


def persist(service: "Workflow", workspace: str, qid: str, request: PlanRequest | None = None):
    service.editable(service.ws(workspace))
    state = preview(service, workspace, qid)
    if state["guide_choice"] and not state["guide_choice"]["current"]:
        raise ValueError(state["guide_choice"]["notice"])
    if request and request.expected_revision != state["state_revision"]:
        raise ValueError("문항·가이드 또는 경험이 바뀌었습니다. 현재 작성 설계를 다시 확인해 주세요.")
    emphasis = state["emphasis"]
    notes = state["working_notes"]
    if request:
        if emphasis["state"] == "discarded" and request.emphasis_state != "discarded":
            raise ValueError("폐기한 강조 방향은 자동으로 복원할 수 없습니다.")
        if request.emphasis_state == "active" and not request.emphasis.strip():
            raise ValueError("사용할 강조 방향을 입력해 주세요.")
        emphasis = {"state": request.emphasis_state,
                    "text": "" if request.emphasis_state == "discarded" else request.emphasis.strip()}
        notes = request.working_notes.strip()
        if request.emphasis_state == "discarded":
            for previous in service.db.scalars(select(Artifact).where(
                Artifact.user_id == service.user, Artifact.workspace_id == workspace,
                Artifact.kind == "WritingPlan", Artifact.slot == qid,
            )):
                previous.data = {**previous.data, "emphasis": {"state": "discarded", "text": ""}}
    if (state["plan_current"] and state["emphasis"] == emphasis and state["working_notes"] == notes):
        return service.artifact(workspace, "WritingPlan", qid)
    guide = state["guide"]
    source, _ = register_source(service.db, service.user, f"writing-guide/{guide['guide_id']}",
                                json.dumps(guide, ensure_ascii=False, sort_keys=True), "REFERENCE",
                                {"title": guide["label"], "fact_authority": False})
    deps = list(state["_guide_deps"])
    for kind in ("ApplicationBrief", "EvidencePack"):
        item = latest(service.db, service.user, workspace, kind, required=False)
        if item and item.status in {"ACTIVE", "LOCKED"}:
            deps.append(item.id)
    selection = latest(service.db, service.user, workspace, "ExperienceSelection", qid, required=False)
    if selection and selection.status in {"ACTIVE", "LOCKED"}:
        deps.append(selection.id)
    data = {
        "question": state["question"], "guide": guide,
        "guide_snapshot_sha256": state["guide_snapshot_sha256"],
        "input_revision": state["state_revision"], "emphasis": emphasis,
        "working_notes": notes, "notes_are_verified_facts": False,
        "guide_choice": state["guide_choice"],
        "evidence_ids": state["_evidence_ids"], "version": VERSION,
    }
    item, _ = save(service.db, service.user, workspace, "WritingPlan", data, deps=deps,
                   sources=sorted(set([source.id, *state["_source_ids"]])), slot=qid)
    return item


def context(plan) -> dict:
    """Same guide used by the screen; examples and working notes have no fact authority."""
    guide = publishable_guide(plan.data["guide"])
    return {
        "plan_id": plan.id, "plan_version": plan.version,
        "guide_snapshot_sha256": digest(guide),
        "guide": guide,
        "emphasis": (plan.data["emphasis"]["text"] if plan.data["emphasis"]["state"] == "active" else None),
        "working_notes": plan.data["working_notes"], "notes_are_verified_facts": False,
        "reference_examples_are_applicant_facts": False,
    }


def require_current(service: "Workflow", workspace: str, qid: str, brief):
    plan_id = brief.data.get("writing_plan_id")
    if not plan_id and not any(latest(service.db, service.user, workspace, kind, qid, required=False)
                              for kind in ("QuestionContract", "GuideChoice")):
        return None
    state = preview(service, workspace, qid)
    if state["guide_choice"]:
        if not state["guide_choice"]["current"] or not plan_id:
            raise ValueError("문항 기준이나 가이드 선택을 현재 메시지에 반영하고 다시 승인해 주세요.")
        execution_ready_guide(state["guide"])
    if not plan_id:  # Already-created legacy briefs remain usable.
        return None
    if not state["plan_current"] or state["plan"]["id"] != plan_id:
        raise ValueError("작성 설계가 바뀌었습니다. 문항 메시지와 근거를 다시 확인해 주세요.")
    plan = service.artifact(workspace, "WritingPlan", qid)
    return plan


def execution_ready_guide(guide):
    """A clarified form counter must never silently fall back to the legacy character QA."""
    contract = guide.get("question_contract")
    if contract:
        policy = contract["length"]
        if policy["unit"] != "CHARACTERS" or any(policy[key] == "EXCLUDED" for key in ("spaces", "newlines", "title")):
            raise ValueError("이 제출 폼의 계수 방식은 현재 자동 검증을 지원하지 않습니다. 가이드는 저장되지만 자동 작성·잠금은 보류됩니다.")


def validate_plan_text(plan, text):
    execution_ready_guide(plan.data["guide"])
    policy = plan.data["guide"].get("question_contract", {}).get("length")
    if policy and (len(text) > policy["maximum"] or len(text) < (policy["minimum"] or 0)):
        raise ValueError("현재 제출 폼에서 확인한 최소·최대 분량을 맞춰 주세요.")


def approve(service: "Workflow", workspace: str, qid: str, brief):
    plan = require_current(service, workspace, qid, brief)
    if plan:
        lock(service.db, service.user, plan)

