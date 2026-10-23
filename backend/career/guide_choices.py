"""I03 user decisions over server-owned guide data; never an applicant fact approval."""

import os
from pathlib import Path
from typing import Annotated

from pydantic import Field, model_validator
from sqlalchemy import select

from career.artifacts import fresh, latest, save, stale
from career.models import Artifact
from career.question_contracts import Contract, LengthPolicy, QuestionContract, Text, fingerprint
from career.question_guide_import import ReleaseLedger, load_catalog, read_json
from career.question_guide_search import retrieve
from career.truth import register_source

Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Budget = Annotated[int, Field(strict=True, gt=0, le=100000)]


def enabled():
    return os.getenv("CAREER_GUIDE_SELECTION_ENABLED", "0") == "1"


class QuestionConfirmation(Contract):
    expected_revision: Digest
    length: LengthPolicy
    required_demands: tuple[Text, ...] = Field(default=(), max_length=20)
    excluded_topics: tuple[Text, ...] = Field(default=(), max_length=20)
    source_note: str = Field(default="", max_length=500)
    confirmed: bool = Field(strict=True)

    @model_validator(mode="after")
    def direct_confirmation(self):
        if self.confirmed is not True:
            raise ValueError("현재 문항과 제출 폼 기준을 직접 확인해 주세요.")
        return self


class GuideChoiceRequest(Contract):
    expected_revision: Digest
    request_key: Digest
    guide_id: str | None = Field(default=None, min_length=1, max_length=180)
    guide_version: Annotated[int, Field(strict=True, gt=0)] | None = None
    guide_snapshot_hash: Digest | None = None
    allocation_budgets: tuple[Budget, ...] | None = Field(default=None, min_length=1, max_length=12)

    @model_validator(mode="after")
    def complete_reference(self):
        if (self.guide_id is None) != (self.guide_version is None) or (
                self.guide_id is None) != (self.guide_snapshot_hash is None):
            raise ValueError("가이드 ID·버전·내용 지문을 함께 확인해 주세요.")
        return self


def catalog_snapshot():
    """Only operator-configured local files; no client paths or remote retrieval."""
    directory, ledger = os.getenv("CAREER_GUIDE_CATALOG_DIR"), os.getenv("CAREER_GUIDE_RELEASES_PATH")
    try:
        records = load_catalog(Path(directory)) if directory else ()
        reviews = ReleaseLedger.model_validate(read_json(Path(ledger))).reviews if ledger else ()
        return records, reviews, "CONFIGURED" if directory else "EMPTY"
    except (OSError, ValueError, KeyError):
        return (), (), "UNAVAILABLE"  # Never echo filesystem paths or private curator data.


def contract_state(service, workspace, qid):
    ws, question = service.ws(workspace), service.question(workspace, qid)
    base = fingerprint([ws.company, ws.role, question])
    stored = latest(service.db, service.user, workspace, "QuestionContract", qid, required=False)
    current = bool(stored and stored.status in {"ACTIVE", "LOCKED"} and stored.data["base_revision"] == base)
    if current and stored:
        try:
            fresh(service.db, service.user, stored)
        except (ValueError, LookupError):
            current = False
    values = {"application_id": workspace, "question_id": qid, "company": ws.company, "role": ws.role,
              "raw_text": question["text"], "length": {"maximum": question["limit"]}}
    if current and stored:
        values.update(stored.data["contract"])
    contract = QuestionContract.model_validate(values)
    revision = fingerprint([base, contract.model_dump(mode="json"),
                            [stored.id, stored.version, stored.status] if stored else None])
    return {"contract": contract, "state_revision": revision, "base_revision": base,
            "artifact": stored, "current": current, "needs_reconfirmation": bool(stored and not current),
            "source": {"kind": "CURRENT_WORKSPACE_QUESTION", "workspace_id": workspace, "question_id": qid,
                       "confirmed_artifact_id": stored.id if current and stored else None}}


def _invalidate_plan(service, workspace, qid):
    plan = latest(service.db, service.user, workspace, "WritingPlan", qid, required=False)
    if plan and plan.status in {"ACTIVE", "LOCKED"}:
        plan.status = "STALE"
        stale(service.db, service.user, [plan.id])


def _replay(service, workspace, qid, kind, request_id, request):
    request_hash = fingerprint(request.model_dump(mode="json"))
    previous = service.db.scalar(select(Artifact).where(Artifact.user_id == service.user,
        Artifact.workspace_id == workspace, Artifact.kind == kind, Artifact.slot == qid,
        Artifact.data["request_id"].as_string() == request_id))
    if previous:
        if previous.data["request_hash"] != request_hash:
            raise ValueError("같은 요청 키로 다른 내용을 저장할 수 없습니다.")
        return previous, request_hash
    return None, request_hash


def confirm_question(service, workspace, qid, request: QuestionConfirmation, request_id: str):
    service.editable(service.ws(workspace))
    state = contract_state(service, workspace, qid)
    previous, request_hash = _replay(service, workspace, qid, "QuestionContract", request_id, request)
    if previous:
        return previous
    if request.expected_revision != state["state_revision"]:
        raise ValueError("문항 기준이 바뀌었습니다. 현재 문항을 다시 확인해 주세요.")
    question = service.question(workspace, qid)
    if request.length.maximum != question["limit"]:
        raise ValueError("글자 수 상한은 현재 등록한 문항의 제한과 일치해야 합니다.")
    contract = state["contract"].model_copy(update={
        "version": state["artifact"].version + 1 if state["artifact"] else 1,
        "length": request.length, "required_demands": request.required_demands,
        "excluded_topics": request.excluded_topics, "verified_status": "USER_CONFIRMED"})
    source, _ = register_source(service.db, service.user, f"question-contract/{workspace}/{qid}",
        contract.model_dump_json(), "REFERENCE", {"fact_authority": False, "source_note": request.source_note,
                                                   "verification": "USER_CONFIRMED_NOT_LIVE_VERIFIED"})
    result, _ = save(service.db, service.user, workspace, "QuestionContract", {
        "base_revision": state["base_revision"], "contract": contract.model_dump(mode="json"),
        "request_id": request_id, "request_hash": request_hash}, sources=[source.id], slot=qid)
    _invalidate_plan(service, workspace, qid)
    return result


def _fallback(question, template):
    from career.writing_plans import RULES

    return {"guide_id": f"i03-template:{template['family']}", "guide_version": 1,
            "origin": "SUGGESTED_STRUCTURE", "label": "현재 문항에 맞춘 제안 구성",
            "question": question.raw_text, "question_intent": template["intent"],
            "question_type": template["family"], "actual_limit": question.length.model_dump(mode="json"),
            "allocation": [{"order": i + 1, "content": part["content"],
                            "approximate_characters": part["suggested_budget"], "what_to_write": part["hint"]}
                           for i, part in enumerate(template["allocation"])],
            "writing_strategy": [{"instruction": text} for text in RULES], "skill_rules": RULES,
            "reference_example": {"origin": "STRUCTURE_TEMPLATE_NOT_ACTUAL_APPLICATION", "paragraphs": [],
                                  "use_as_applicant_fact": False}, "source": None,
            "fixed_body_paragraph_count": False}


def _candidate_guide(question, candidate, reviews):
    review = next(r for r in reviews if r.guide_id == candidate["guide_id"]
                  and r.version == candidate["guide_version"] and r.content_hash == candidate["guide_snapshot_hash"])
    return {"guide_id": candidate["guide_id"], "guide_version": candidate["guide_version"],
            "origin": "SELECTED_GUIDE_REFERENCE", "label": "선택한 구조 참고" if candidate["match_type"] == "EXACT"
            else "다른 문항에서 참고한 제안 구성", "match_type": candidate["match_type"],
            "match_policy": candidate["match_policy"], "question": question.raw_text,
            "question_intent": candidate["intent"], "actual_limit": question.length.model_dump(mode="json"),
            "source_content_hash": candidate["guide_snapshot_hash"], "source_manifest": candidate["source_manifest"],
            "review_revision": fingerprint(review.model_dump(mode="json")), "warnings": candidate["warnings"],
            "count_policy_confirmation_required": candidate["count_policy_confirmation_required"],
            "allocation": [{"order": i + 1, "content": part["content"], "approximate_characters": part["suggested_budget"],
                            "what_to_write": "현재 확인된 본인 경험으로 이 기능을 채워 주세요."}
                           for i, part in enumerate(candidate["suggested_allocation"])],
            "writing_strategy": [{"instruction": text} for text in candidate["warnings"]],
            "skill_rules": [], "source": {"source_url": candidate["source_ref"]},
            "reference_example": {"origin": "WITHHELD_RIGHTS_PENDING", "paragraphs": [],
                                  "use_as_applicant_fact": False, "notice": "예시 전문은 제공하지 않습니다. 구조만 참고해 주세요."},
            "fixed_body_paragraph_count": False}


def _search(service, workspace, qid):
    state = contract_state(service, workspace, qid)
    records, reviews, availability = catalog_snapshot()
    result = retrieve(state["contract"], records, releases=reviews, enabled=True)
    return state, result, reviews, availability


def resolve(service, workspace, qid, legacy):
    """GET may show a safe current fallback; execution must reject a stale decision."""
    choice = latest(service.db, service.user, workspace, "GuideChoice", qid, required=False)
    contract = latest(service.db, service.user, workspace, "QuestionContract", qid, required=False)
    if not choice and not contract:
        return legacy, {}, []
    state, result, reviews, availability = _search(service, workspace, qid)
    current = not state["needs_reconfirmation"]
    guide = _fallback(state["contract"], result["fallback"])
    if choice:
        current = current and choice.status in {"ACTIVE", "LOCKED"}
        try:
            fresh(service.db, service.user, choice)
        except (ValueError, LookupError):
            current = False
        candidate = next((c for c in result["candidates"] if c["guide_id"] == choice.data["guide_id"]
            and c["guide_version"] == choice.data["guide_version"]
            and c["guide_snapshot_hash"] == choice.data["source_content_hash"]), None)
        base = _candidate_guide(state["contract"], candidate, reviews) if candidate else guide
        current = current and choice.data["question_revision"] == state["contract"].revision
        current = current and choice.data["base_guide_hash"] == fingerprint(base)
        if choice.data["guide_id"] is not None and (candidate is None or availability == "UNAVAILABLE"):
            current = False
        if current:
            guide = base
            for part, budget in zip(guide["allocation"], choice.data["allocation_budgets"], strict=True):
                part["approximate_characters"] = budget
    guide["question_contract"] = state["contract"].model_dump(mode="json")
    metadata = {"current": current, "choice_id": choice.id if choice else None,
                "choice_version": choice.version if choice else None,
                "guide_id": choice.data["guide_id"] if choice else None,
                "allocation_budgets": choice.data["allocation_budgets"] if choice and current else None,
                "question_revision": state["contract"].revision,
                "notice": None if current else "문항 또는 선택한 가이드가 바뀌었습니다. 다시 확인하고 선택해 주세요."}
    deps = [item.id for item in (contract, choice) if item]
    return guide, metadata, deps


def search_preview(service, workspace, qid):
    from career.writing_plans import public_preview

    state, result, _, availability = _search(service, workspace, qid)
    writing = public_preview(service, workspace, qid)
    return {"question_contract": state["contract"].model_dump(mode="json"),
            "contract_state_revision": state["state_revision"], "question_source": state["source"],
            "needs_reconfirmation": state["needs_reconfirmation"], "catalog_status": availability,
            "selection_revision": writing["state_revision"], "selection": writing.get("guide_choice"),
            "retrieval": result, "can_execute": False}


def select_guide(service, workspace, qid, request: GuideChoiceRequest, request_id: str):
    from career.writing_plans import persist

    service.editable(service.ws(workspace))
    service.question(workspace, qid)
    previous, request_hash = _replay(service, workspace, qid, "GuideChoice", request_id, request)
    if previous:
        return previous
    state, result, reviews, _ = _search(service, workspace, qid)
    preview = search_preview(service, workspace, qid)
    if (state["needs_reconfirmation"] or request.expected_revision != preview["selection_revision"]
            or request.request_key != result["request_key"]):
        raise ValueError("문항·가이드·경험 기준이 바뀌었습니다. 새로 불러온 뒤 다시 선택해 주세요.")
    candidate = next((c for c in result["candidates"] if c["guide_id"] == request.guide_id
        and c["guide_version"] == request.guide_version and c["guide_snapshot_hash"] == request.guide_snapshot_hash), None)
    if request.guide_id is not None and candidate is None:
        raise ValueError("현재 문항에 적합하고 검토된 가이드만 선택할 수 있습니다.")
    guide = _candidate_guide(state["contract"], candidate, reviews) if candidate else _fallback(state["contract"], result["fallback"])
    budgets = request.allocation_budgets or tuple(part["approximate_characters"] for part in guide["allocation"])
    if (len(budgets) != len(guide["allocation"]) or sum(budgets) > state["contract"].length.maximum
            or sum(budgets) < (state["contract"].length.minimum or 0)):
        raise ValueError("문항의 구성 수와 현재 제한 안에서 분량을 배분해 주세요.")
    source, _ = register_source(service.db, service.user, f"guide-choice/{workspace}/{qid}",
        fingerprint(guide), "REFERENCE", {"fact_authority": False, "external_example_mode": "NONE"})
    deps = [state["artifact"].id] if state["current"] and state["artifact"] else []
    choice, _ = save(service.db, service.user, workspace, "GuideChoice", {
        "guide_id": request.guide_id, "guide_version": request.guide_version,
        "source_content_hash": request.guide_snapshot_hash, "base_guide_hash": fingerprint(guide),
        "question_revision": state["contract"].revision, "request_key": result["request_key"],
        "allocation_budgets": list(budgets), "request_id": request_id, "request_hash": request_hash,
        "decision": "STRUCTURE_CHOSEN_NOT_CLAIM_APPROVAL"}, deps=deps, sources=[source.id], slot=qid)
    _invalidate_plan(service, workspace, qid)
    persist(service, workspace, qid)
    return choice
