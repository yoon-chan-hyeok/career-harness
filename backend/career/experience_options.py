"""Bounded, proof-backed alternatives and durable human experience choices."""

import json
import re
from copy import deepcopy
from hashlib import sha256
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from career.artifacts import fresh, latest, save, stale
from career.models import Artifact, Evidence, Source
from career.resume_layout import rank_evidence
from career.truth import owned, view
from career.validation import GOOD

if TYPE_CHECKING:
    from career.workflow import Workflow


class ExperienceChoiceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    slot: str = Field(default="strategy", min_length=1, max_length=100)
    evidence_id: str = Field(min_length=1, max_length=64)
    base_artifact_id: str = Field(min_length=1, max_length=64)
    base_artifact_version: int = Field(ge=1)
    options_revision: str = Field(pattern=r"^[a-f0-9]{64}$")


def fingerprint(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def evidence_fingerprint(item: Evidence) -> str:
    return fingerprint([item.id, item.source_id, item.kind, item.status, item.title, item.body, item.data])


def usable_ownership(item: Evidence) -> bool:
    ownership = item.data.get("ownership", {})
    return isinstance(ownership, dict) and ownership.get("implementation") in {
        "USER", "USER_AI_ASSISTED", "USER_MODIFIED_EXISTING_CODE", "TEAM", "LAB"}


def experience_key(item: Evidence) -> str:
    original = item.data.get("original", {})
    original = original if isinstance(original, dict) else {}
    value = next((item.data[key] for key in ("project_id", "experience_id", "project_name")
                  if isinstance(item.data.get(key), str) and item.data[key].strip()), None)
    value = value or original.get("scope") or item.title
    return re.sub(r"\s+", " ", str(value)).strip().casefold()


def active_selection(service: "Workflow", workspace: str, slot: str, *, fallback=False) -> Artifact | None:
    selection = latest(service.db, service.user, workspace, "ExperienceSelection", slot, required=False)
    if selection is None and fallback and slot != "strategy":
        selection = latest(service.db, service.user, workspace, "ExperienceSelection", "strategy", required=False)
    if selection is None:
        return None
    fresh(service.db, service.user, selection)
    evidence = owned(service.db, Evidence, service.user, selection.data["evidence_id"])
    service.selected([evidence.id])
    if not usable_ownership(evidence):
        raise ValueError("선택한 경험의 본인 수행 범위를 확인하고 다시 선택해 주세요.")
    if evidence_fingerprint(evidence) != selection.data["evidence_fingerprint"]:
        raise ValueError("선택한 경험의 내용이 바뀌었습니다. 현재 추천 근거를 확인하고 다시 선택해 주세요.")
    pack = service.artifact(workspace, "EvidencePack")
    allowed = {i["evidence_id"] for i in pack.data["items"] if i["classification"] != "NO_EVIDENCE"}
    if evidence.id not in allowed:
        raise ValueError("선택 경험을 현재 직무 근거 매핑에서 다시 확인해 주세요.")
    return selection


def selection_context(selection: Artifact | None) -> dict[str, Any] | None:
    if selection is None:
        return None
    return {"artifact_id": selection.id, "version": selection.version,
            "evidence_id": selection.data["evidence_id"], "slot": selection.slot,
            "option": deepcopy(selection.data["option"]),
            "instruction": "Use the user's chosen verified experience. This choice is not claim or strategy approval."}


def _usage(service: "Workflow", workspace: str, slot: str) -> dict[str, set[str]]:
    current: dict[tuple[str, str], Artifact] = {}
    for artifact in service.db.scalars(select(Artifact).where(
        Artifact.user_id == service.user, Artifact.workspace_id == workspace,
        Artifact.kind.in_(["QuestionBrief", "ResumeBrief", "QuestionPortfolio"]),
    ).order_by(Artifact.version)):
        current[(artifact.kind, artifact.slot)] = artifact
    usage: dict[str, set[str]] = {}
    for artifact in current.values():
        if artifact.status not in {"ACTIVE", "LOCKED"}:
            continue
        if artifact.kind == "QuestionPortfolio":
            if artifact.status != "LOCKED":
                continue
            pairs = [(i["question_id"], i["evidence_candidate_ids"]) for i in artifact.data["items"]]
        else:
            pairs = [(artifact.slot or "resume", artifact.data.get(
                "evidence_ids" if artifact.kind == "QuestionBrief" else "selected_evidence_ids", []))]
        for used_slot, identifiers in pairs:
            if used_slot != slot:
                for ident in identifiers:
                    usage.setdefault(ident, set()).add(used_slot)
    return usage


def options(service: "Workflow", workspace: str, slot="strategy") -> dict[str, Any]:
    ws = service.ws(workspace)
    question = None if slot in {"strategy", "resume"} else service.question(workspace, slot)
    opportunity = service.artifact(workspace, "OpportunityBrief")
    pack = service.artifact(workspace, "EvidencePack")
    strategy = latest(service.db, service.user, workspace, "ApplicationBrief", required=False)
    identifiers = list(dict.fromkeys(i["evidence_id"] for i in pack.data["items"]
                                    if i["classification"] != "NO_EVIDENCE"))
    eligible = []
    states = []
    for ident in identifiers:
        # Fail closed even when a corrupted mapping references someone else's row.
        item = owned(service.db, Evidence, service.user, ident)
        source = owned(service.db, Source, service.user, item.source_id)
        states.append([evidence_fingerprint(item), source.id, source.status, source.content_hash])
        if (item.status in GOOD and item.kind != "EXPRESSION" and source.status in GOOD
                and usable_ownership(item)):
            eligible.append(item)
    by_id = {item.id: item for item in eligible}
    mapped = [i for i in pack.data["items"] if i["evidence_id"] in by_id]
    ranking = rank_evidence(opportunity.data, mapped, service.selected(list(by_id)))
    tokens = list(dict.fromkeys(re.findall(r"[\w가-힣]+", question["text"].lower()))) if question else []
    question_matches = {item.id: sum(token in (item.title + " " + item.body).lower() for token in tokens)
                        for item in eligible}
    if question:
        # Keep the existing actual-output/Direct ranking; question wording only
        # breaks ties within the same mapped classification and skill focus.
        ranking.sort(key=lambda row: (row["skill_focus"] != "MAIN_SKILL",
                                     row["classification"] != "DIRECT", -question_matches[row["evidence_id"]],
                                     row["rank"]))
    usage = _usage(service, workspace, slot)
    project_usage: dict[str, set[str]] = {}
    for item in eligible:
        project_usage.setdefault(experience_key(item), set()).update(usage.get(item.id, set()))
    results = []
    seen_experiences: set[str] = set()
    seen_bodies: set[str] = set()
    for row in ranking:
        evidence = by_id[row["evidence_id"]]
        source = owned(service.db, Source, service.user, evidence.source_id)
        source_title = next((source.data[name] for name in ("title", "filename", "source_title")
                             if isinstance(source.data.get(name), str) and source.data[name].strip()), None)
        source_title = source_title or source.path.replace("\\", "/").rsplit("/", 1)[-1] or "연결된 원자료"
        key = experience_key(evidence)
        body_key = re.sub(r"\s+", " ", evidence.body).strip().casefold()
        if key in seen_experiences or body_key in seen_bodies:
            continue
        seen_experiences.add(key)
        seen_bodies.add(body_key)
        ownership = evidence.data.get("ownership", {})
        ownership = ownership if isinstance(ownership, dict) else {}
        strengths = ["현재 직무의 직접 근거" if row["classification"] == "DIRECT" else "현재 직무의 인접 근거"]
        gaps = []
        if row["evidence_strength"] == "STRONG":
            strengths.append("근거 매핑에서 증거 강도가 높음")
        if ownership.get("implementation", "UNKNOWN") == "USER":
            strengths.append("본인 수행 범위가 확인됨")
        elif ownership.get("implementation", "UNKNOWN") in {"", "UNKNOWN", None}:
            gaps.append("본인 수행 범위 확인 필요: 팀 전체 기여로 확대하지 않기")
        else:
            gaps.append("공동·타인 수행 범위를 본인 단독 수행으로 표현하지 않기")
        if row["classification"] != "DIRECT":
            gaps.append("직접 경험과 직무에 적용 가능한 경험을 구별하기")
        if row["evidence_strength"] in {"LIMITED", "NONE"}:
            gaps.append("직무 산출물에 대한 증거 보강 필요")
        if not row["concrete_output"]:
            gaps.append("구체적인 산출물·수치의 원자료 확인 필요")
        gaps.extend("표현 금지: " + str(claim) for claim in evidence.data.get("forbidden_claims", []))
        reason = "현재 근거 매핑: " + row["rationale"]
        if question and question_matches[evidence.id]:
            reason += " · 문항 표현과 실제 경험 원문의 연결을 함께 검토했습니다."
        results.append({"rank": len(results) + 1, "evidence_id": evidence.id, "title": evidence.title,
                        "source_ids": [evidence.source_id], "classification": row["classification"],
                        "sources": [{"id": source.id, "title": source_title, "status": source.status}],
                        "recommendation_reason": reason, "strengths": strengths, "gaps": gaps,
                        "recommended": not results, "used_in_slots": sorted(project_usage.get(key, set())),
                        "usage_count": len(project_usage.get(key, set()))})
        if len(results) == 3:
            break
    selection = latest(service.db, service.user, workspace, "ExperienceSelection", slot, required=False)
    if selection is None and slot != "strategy":
        selection = latest(service.db, service.user, workspace, "ExperienceSelection", "strategy", required=False)
    selected_id = None
    selection_status = selection.status if selection else None
    if selection and selection.status in {"ACTIVE", "LOCKED"}:
        try:
            active_selection(service, workspace, slot, fallback=True)
            selected_id = selection.data["evidence_id"]
        except ValueError:
            selection_status = "STALE"
    revision = fingerprint({"workspace": workspace, "slot": slot, "question": question,
                            "opportunity": [opportunity.id, opportunity.version, opportunity.status],
                            "pack": [pack.id, pack.version, pack.status],
                            "strategy": [strategy.id, strategy.version, strategy.status] if strategy else None,
                            "evidence_states": states, "options": results})
    return {"workspace_id": ws.id, "slot": slot, "base_artifact_id": pack.id,
            "base_artifact_version": pack.version, "options_revision": revision, "options": results,
            "recommended_evidence_id": results[0]["evidence_id"] if results else None,
            "selected_evidence_id": selected_id, "selection_artifact_id": selection.id if selection else None,
            "selection_status": selection_status,
            "inherited_from": selection.slot if selection and selection.slot != slot else None,
            "notice": "확인된 현재 직무 근거에서 최대 3개를 제안합니다. 추천·경험 선택은 전략·문항 승인과 별개이며, 부족한 경험을 만들어 채우지 않습니다."}


def choose(service: "Workflow", workspace: str, request: ExperienceChoiceRequest) -> dict[str, Any]:
    ws = service.ws(workspace)
    service.editable(ws)
    current = options(service, workspace, request.slot)
    if (current["base_artifact_id"] != request.base_artifact_id
            or current["base_artifact_version"] != request.base_artifact_version
            or current["options_revision"] != request.options_revision):
        raise ValueError("추천 기준 또는 근거 버전이 바뀌었습니다. 현재 경험 후보를 다시 확인해 주세요.")
    option = next((item for item in current["options"] if item["evidence_id"] == request.evidence_id), None)
    if option is None:
        raise ValueError("현재 추천 목록에 있는 본인의 확인된 경험을 선택해 주세요.")
    old = latest(service.db, service.user, workspace, "ExperienceSelection", request.slot, required=False)
    if old and current["selected_evidence_id"] == request.evidence_id:
        return {"selection": view(old), "stale_artifacts": [], "requires_approval": True,
                "next_step": "선택 경험을 반영한 전략·문항 메시지를 확인하고 승인해 주세요."}
    evidence = owned(service.db, Evidence, service.user, request.evidence_id)
    opportunity = service.artifact(workspace, "OpportunityBrief")
    data = {"evidence_id": evidence.id, "evidence_fingerprint": evidence_fingerprint(evidence),
            "option": deepcopy(option), "recommended_evidence_id": current["recommended_evidence_id"],
            "options_revision": current["options_revision"], "base_artifact_id": request.base_artifact_id,
            "base_artifact_version": request.base_artifact_version,
            "opportunity_artifact_id": opportunity.id, "opportunity_artifact_version": opportunity.version,
            "choice_origin": "EXPLICIT_USER_SELECTION", "approval_granted": False}
    selection, changed = save(service.db, service.user, workspace, "ExperienceSelection", data,
                              deps=[request.base_artifact_id, opportunity.id], sources=[evidence.source_id],
                              slot=request.slot)
    affected_kind = {"strategy": "ApplicationBrief", "resume": "ResumeBrief"}.get(request.slot, "QuestionBrief")
    affected_slot = "" if request.slot in {"strategy", "resume"} else request.slot
    affected = latest(service.db, service.user, workspace, affected_kind, affected_slot, required=False)
    if affected and affected.status in {"ACTIVE", "LOCKED"}:
        changed += stale(service.db, service.user, [affected.id])
        affected.status = "STALE"
        changed.append(affected.id)
    if request.slot == "strategy":
        ws.state = "EVIDENCE_READY"
    elif request.slot == "resume":
        service.resume_state(workspace, "NEW")
        ws.state = "COMPOSING"
    else:
        service.question_state(workspace, request.slot, "NEW")
        ws.state = "COMPOSING"
    return {"selection": view(selection), "stale_artifacts": list(dict.fromkeys(changed)),
            "requires_approval": True,
            "next_step": "선택 경험을 반영해 전략을 다시 구성하고 승인해 주세요." if request.slot == "strategy"
            else "선택 경험을 우선 배치해 이력서를 다시 작성·검수해 주세요." if request.slot == "resume"
            else "선택 경험으로 문항 메시지를 다시 구성하고 승인한 뒤 작성해 주세요."}
