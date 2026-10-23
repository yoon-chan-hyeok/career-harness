"""I04 scoped proposals and human decisions over existing guides and applicant truth."""

import os
from typing import Annotated, Literal

from pydantic import Field, model_validator
from sqlalchemy import select

from career.artifacts import fresh, latest, lock, save, stale
from career.experience_options import active_selection, evidence_fingerprint, experience_key, usable_ownership
from career.guide_choices import Digest, _replay, resolve
from career.models import Artifact, Evidence, Source
from career.question_contracts import Contract, Text, fingerprint, normalized
from career.scoped_context import ContextRequest, compile_task_context
from career.token_estimation import gpt_oss_input_tokens
from career.truth import owned
from career.v3_preview import RECORD_TYPES
from career.validation import GOOD

Id = Annotated[str, Field(min_length=1, max_length=200)]
Disposition = Literal["ACCEPT", "MODIFY", "COMBINE", "DIRECT", "REJECT", "HOLD"]
ACCEPTED = {"ACCEPT", "MODIFY", "COMBINE", "DIRECT"}


def enabled():
    return os.getenv("CAREER_JOINT_PORTFOLIO_ENABLED", "0") == "1"


class ProposalRequest(Contract):
    expected_revision: Digest
    use_ai: bool = Field(default=False, strict=True)
    external_transfer_confirmed: bool = Field(default=False, strict=True)
    max_input_tokens: Annotated[int, Field(strict=True, ge=1, le=32768)] = 8192

    @model_validator(mode="after")
    def explicit_transfer(self):
        if self.use_ai and not self.external_transfer_confirmed:
            raise ValueError("현재 문항·본인 근거를 연결된 AI로 보내 제안받는 요청인지 확인해 주세요.")
        return self


class PersonaCandidate(Contract):
    text: Text
    evidence_ids: tuple[Id, ...] = Field(max_length=20)
    limitation: Text


class Material(Contract):
    question_id: Id
    identity_role: Text
    primary_message: Text
    evidence_ids: tuple[Id, ...] = Field(max_length=5)
    evidence_role: Text
    metric_ids: tuple[Id, ...] = Field(default=(), max_length=10)
    climax: Text


class JointProposal(Contract):
    personas: tuple[PersonaCandidate, ...] = Field(min_length=1, max_length=3)
    items: tuple[Material, ...] = Field(min_length=1, max_length=20)


class DecisionRequest(Contract):
    expected_revision: Digest
    proposal_id: Id
    proposal_version: Annotated[int, Field(strict=True, gt=0)]
    disposition: Disposition
    persona_candidate_ids: tuple[Id, ...] = Field(default=(), max_length=3)
    persona_text: str = Field(default="", max_length=2000)
    items: tuple[Material, ...] = Field(default=(), max_length=20)
    reason: str = Field(default="", max_length=2000)


def _row_revision(row):
    from career.v3_preview import digest

    return digest({col.name: getattr(row, col.name) for col in row.__table__.columns})


def inputs(service, workspace):
    """Read-only snapshot. No provider, approval, new Truth copy or silent candidate replacement."""
    from career.writing_plans import guide_for, publishable_guide

    ws = service.ws(workspace)
    if any(latest(service.db, service.user, workspace, kind, required=False) is None
           for kind in ("ApplicationBrief", "EvidencePack")):
        raise ValueError("직무 분석과 근거 연결을 마치고 지원 전략을 승인하면 소재 배분을 시작할 수 있습니다.")
    strategy = service.artifact(workspace, "ApplicationBrief")
    pack = service.artifact(workspace, "EvidencePack")
    questions = ws.data.get("questions", [])
    if not questions or len(questions) > 20:
        raise ValueError("문항을 1~20개 등록하고 배분해 주세요.")
    identifiers = sorted({i["evidence_id"] for i in pack.data["items"]})
    if len(identifiers) > 20:
        raise ValueError("필수 근거가 20개를 넘습니다. 근거 매핑 범위를 직접 조정해 주세요.")
    refs, sources, candidates, guides, selections, deps = [], set(), [], {}, {}, [strategy.id, pack.id]
    from career.entities import WritingRuleRecord

    # Bind preference/reference revisions without promoting or applying new rules.
    for row in service.db.scalars(select(WritingRuleRecord).where(WritingRuleRecord.user_id == service.user,
            WritingRuleRecord.status.in_(["CANONICAL", "VERIFIED"])).order_by(WritingRuleRecord.id)):
        refs.append(_row_revision(row))
        if row.source_id:
            refs.append(_row_revision(owned(service.db, Source, service.user, row.source_id)))
    for ident in service.reference_sources("joint_portfolio"):
        source = owned(service.db, Source, service.user, ident)
        refs.append(_row_revision(source))
        sources.add(ident)
    holds = [] if strategy.status == "LOCKED" else ["현재 지원 전략을 먼저 승인해 주세요."]
    for ident in identifiers:
        evidence = owned(service.db, Evidence, service.user, ident)
        source = owned(service.db, Source, service.user, evidence.source_id)
        mappings = [i for i in pack.data["items"] if i["evidence_id"] == ident]
        classifications = {i["classification"] for i in mappings}
        classification = "DIRECT" if "DIRECT" in classifications else "ADJACENT" if "ADJACENT" in classifications else "NO_EVIDENCE"
        reasons = []
        if (evidence.kind == "EXPRESSION" or source.authority == "REFERENCE"
                or evidence.status not in GOOD or source.status not in GOOD):
            reasons.append("현재 사용 가능한 본인 경험 원자료가 필요합니다.")
        if not usable_ownership(evidence):
            reasons.append("본인 수행 범위를 확인해야 합니다.")
        if classification == "NO_EVIDENCE":
            reasons.append("현재 직무의 직접·인접 근거로 확인되지 않았습니다.")
        metrics = []
        refs.extend([_row_revision(evidence), _row_revision(source)])
        candidate_sources = {source.id}
        for kind, model in RECORD_TYPES:
            for row in service.db.scalars(select(model).where(model.user_id == service.user,
                    model.evidence_id == ident, model.status.not_in(["SUPERSEDED", "DO_NOT_USE"])).order_by(model.id)):
                refs.append(_row_revision(row))
                linked = owned(service.db, Source, service.user, row.source_id) if row.source_id else None
                if linked:
                    refs.append(_row_revision(linked))
                    candidate_sources.add(linked.id)
                if row.status not in GOOD or not linked or linked.status not in GOOD or linked.authority == "REFERENCE":
                    reasons.append("연결된 수행 범위·판단·수치의 원자료를 확인해야 합니다.")
                elif kind == "METRIC":
                    metrics.append({"id": row.id, "data": row.data})
        if not reasons:
            sources.update(candidate_sources)
        candidates.append({"evidence_id": ident, "title": evidence.title if evidence.status != "DO_NOT_USE" else "사용 중단 자료",
                           "classification": classification, "eligibility": "HOLD" if reasons else "ELIGIBLE",
                           "limitations": sorted(set(reasons)), "project_key": experience_key(evidence),
                           "job_mappings": [{key: m[key] for key in ("job_output_id", "classification", "rationale", "skill_focus", "concrete_output") if key in m} for m in mappings],
                           "revision": evidence_fingerprint(evidence), "metrics": metrics})
    for q in questions:
        guide, choice, guide_deps = resolve(service, workspace, q["id"], publishable_guide(guide_for(ws.company, ws.role, q)))
        guides[q["id"]] = {"guide": guide, "snapshot_hash": fingerprint(guide), "choice": choice}
        deps.extend(guide_deps)
        if choice and not choice["current"]:
            holds.append(f"{q['text']}: 문항·가이드 기준을 다시 확인해 주세요.")
        selection = active_selection(service, workspace, q["id"], fallback=True)
        selections[q["id"]] = {"id": selection.id, "version": selection.version,
                                "evidence_id": selection.data["evidence_id"]} if selection else None
        if selection:
            deps.append(selection.id)
    snapshot = {"application_id": workspace, "strategy": [strategy.id, strategy.version, strategy.status, _row_revision(strategy)],
                "pack": [pack.id, pack.version, pack.status, _row_revision(pack)], "questions": questions, "guides": guides,
                "candidates": candidates, "uncovered_outputs": pack.data["uncovered_outputs"],
                "truth_revisions": refs, "selections": selections, "holds": holds}
    return {**snapshot, "input_revision": fingerprint(snapshot), "depends_on": sorted(set(deps)),
            "source_ids": sorted(sources), "strategy_data": strategy.data}


def _decision(service, workspace):
    return latest(service.db, service.user, workspace, "MaterialDecision", required=False)


def _current(service, state, artifact):
    try:
        fresh(service.db, service.user, artifact)
        return artifact.data["input_revision"] == state["input_revision"]
    except (ValueError, LookupError):
        return False


def preview(service, workspace):
    state = inputs(service, workspace)
    proposal = latest(service.db, service.user, workspace, "JointPortfolioProposal", required=False)
    decision = _decision(service, workspace)
    persona = latest(service.db, service.user, workspace, "PersonaDecision", required=False)
    portfolio = latest(service.db, service.user, workspace, "QuestionPortfolio", required=False)
    def projection(item):
        return {"id": item.id, "version": item.version, "status": item.status,
                "current": _current(service, state, item), "data": item.data} if item else None
    revision = fingerprint([state["input_revision"],
                            [[a.id, a.version, a.status] if a else None for a in (proposal, decision, persona, portfolio)]])
    return {"application_id": workspace, "input_revision": state["input_revision"], "decision_revision": revision,
            "questions": state["questions"], "guides": state["guides"], "candidates": state["candidates"],
            "strategy": {"positioning": state["strategy_data"]["positioning"],
                         "assignment_statement": state["strategy_data"]["assignment_statement"]},
            "existing_selections": state["selections"], "holds": state["holds"], "proposal": projection(proposal),
            "uncovered_outputs": state["uncovered_outputs"],
            "decision": projection(decision), "persona": projection(persona),
            "portfolio": {"id": portfolio.id, "status": portfolio.status} if portfolio else None,
            "notice": "소재·메시지는 검토 제안입니다. 본인 근거·수행 범위를 바꾸지 않으며 전략 승인과 문항 간 배분 승인은 별개입니다.",
            "can_execute": False}


def _validate_materials(state, items, *, complete):
    qids = {q["id"] for q in state["questions"]}
    if {i.question_id for i in items} != qids or len(items) != len(qids):
        raise ValueError("현재 모든 문항을 한 번씩 배분해 주세요.")
    candidates = {c["evidence_id"]: c for c in state["candidates"]}
    used = {"role": set(), "message": set(), "climax": set(), "metric": set(), "project_role": set()}
    flags = []
    for item in items:
        if len(item.evidence_ids) != len(set(item.evidence_ids)) or len(item.metric_ids) != len(set(item.metric_ids)):
            raise ValueError("같은 근거나 수치를 중복 선택할 수 없습니다.")
        for ident in item.evidence_ids:
            if ident not in candidates or candidates[ident]["eligibility"] != "ELIGIBLE":
                raise ValueError("HOLD: 현재 본인의 수행 범위와 직무 매핑이 확인된 근거를 선택해 주세요.")
        selection = state["selections"][item.question_id]
        if selection and selection["evidence_id"] not in item.evidence_ids:
            raise ValueError("기존에 선택한 경험을 조용히 대체할 수 없습니다. 경험 선택을 먼저 변경해 주세요.")
        if not item.evidence_ids:
            flags.append(f"{item.question_id}: 사용할 근거가 없습니다.")
        allowed_metrics = {m["id"] for ident in item.evidence_ids for m in candidates[ident]["metrics"]}
        if not set(item.metric_ids) <= allowed_metrics:
            raise ValueError("선택한 본인 근거에 연결된 현재 수치만 배분할 수 있습니다.")
        for key, value in (("role", item.identity_role), ("message", item.primary_message), ("climax", item.climax)):
            norm = normalized(value)
            if not norm or norm in used[key]:
                flags.append(f"{item.question_id}: {key} 중복 또는 공백을 수정해 주세요.")
            used[key].add(norm)
        if set(item.metric_ids) & used["metric"]:
            flags.append(f"{item.question_id}: 같은 수치를 여러 문항에 반복 배분했습니다.")
        used["metric"].update(item.metric_ids)
        for project in {candidates[ident]["project_key"] for ident in item.evidence_ids}:
            pair = (project, normalized(item.evidence_role))
            if not pair[1] or pair in used["project_role"]:
                flags.append(f"{item.question_id}: 같은 프로젝트의 근거 역할을 구별해 주세요.")
            used["project_role"].add(pair)
    if complete and flags:
        raise ValueError(" / ".join(flags))
    return flags


def propose(service, workspace, request: ProposalRequest, request_id):
    service.editable(service.ws(workspace))
    previous, request_hash = _replay(service, workspace, "", "JointPortfolioProposal", request_id, request)
    if previous:
        return previous
    state = inputs(service, workspace)
    if request.expected_revision != state["input_revision"] or state["holds"]:
        raise ValueError("문항·전략·가이드·근거 기준을 다시 확인해 주세요.")
    eligible = [c["evidence_id"] for c in state["candidates"] if c["eligibility"] == "ELIGIBLE"]
    context = None
    if request.use_ai:
        pack = compile_task_context(service.db, service.user, ContextRequest(task_type="QUESTION_PORTFOLIO",
            application_id=workspace, required_evidence_ids=tuple(eligible), max_input_tokens=request.max_input_tokens))
        if pack.payload is None:
            raise ValueError("작업 문맥이 보류되었습니다: " + ", ".join(pack.manifest.missing_information))
        structure_guides = {qid: {"snapshot_hash": row["snapshot_hash"], "guide": {
            key: row["guide"][key] for key in ("guide_id", "guide_version", "origin", "question_intent", "allocation",
                "actual_limit", "question_contract", "warnings", "match_policy") if key in row["guide"]}}
            for qid, row in state["guides"].items()}
        context = {"context_pack": pack.payload, "context_manifest": pack.manifest.model_dump(mode="json"),
                   "guides": structure_guides, "candidates": state["candidates"], "existing_selections": state["selections"]}
        if gpt_oss_input_tokens(context) > request.max_input_tokens:
            raise ValueError("필수 문항·가이드·근거를 포함하면 입력 예산을 넘습니다. 범위를 직접 조정해 주세요.")
        value = JointProposal.model_validate(service.ai("joint_portfolio", {
            "task": "Propose applicant-grounded personas and material allocation for every current question. Use only ELIGIBLE applicant evidence IDs and their actual metrics. Guides are structure advice, never applicant facts. Preserve existing user selections. Distinguish messages, evidence roles and climaxes across questions. Do not claim that a proposal is approved.",
            **context}, JointProposal))
    else:
        items = []
        for index, q in enumerate(state["questions"]):
            chosen = state["selections"][q["id"]]
            ids = (chosen["evidence_id"],) if chosen else (eligible[index % len(eligible)],) if eligible else ()
            items.append(Material(question_id=q["id"], identity_role=f"{index + 1}번: {state['guides'][q['id']]['guide']['question_intent']}",
                primary_message=f"{index + 1}번 메시지를 본인 근거로 작성해 주세요.", evidence_ids=ids,
                evidence_role=f"{index + 1}번에서 보여줄 본인 수행을 정해 주세요.", climax=f"{index + 1}번의 핵심 판단·결과를 정해 주세요."))
        value = JointProposal(personas=(PersonaCandidate(text=state["strategy_data"]["positioning"], evidence_ids=tuple(eligible),
            limitation="현재 승인 전략에서 가져온 표현 후보입니다. 소재·메시지는 직접 검토하고 작성해야 합니다."),), items=tuple(items))
    flags = _validate_materials(state, value.items, complete=False)
    allowed = set(eligible)
    if any(not p.text.strip() or not set(p.evidence_ids) <= allowed or (request.use_ai and not p.evidence_ids) for p in value.personas):
        raise ValueError("Persona에는 현재 본인의 확인된 근거만 연결할 수 있습니다.")
    personas = [{**p.model_dump(mode="json"), "candidate_id": fingerprint([state["input_revision"], index, p.model_dump(mode="json")])}
                for index, p in enumerate(value.personas)]
    result, _ = save(service.db, service.user, workspace, "JointPortfolioProposal", {
        "input_revision": state["input_revision"], "personas": personas,
        "items": [i.model_dump(mode="json") for i in value.items], "warnings": flags,
        "proposal_mode": "AI_PROPOSED" if request.use_ai else "OFFLINE_WORKSHEET_NOT_GENERATED_CLAIMS",
        "external_transfer_confirmed": request.external_transfer_confirmed if request.use_ai else False,
        "needs_user_edit": not request.use_ai, "selected": False, "context_manifest": context["context_manifest"] if context else None,
        "semantic_distinctness": "NOT_VERIFIED_BY_STRING_CHECKS",
        "request_id": request_id, "request_hash": request_hash}, deps=state["depends_on"], sources=state["source_ids"],
        model=service.current_model if request.use_ai else "offline-worksheet")
    return result


def _invalidate(service, workspace):
    for kind in ("QuestionPortfolio", "WritingPlan", "QuestionBrief"):
        for item in service.db.scalars(select(Artifact).where(
                Artifact.user_id == service.user, Artifact.workspace_id == workspace, Artifact.kind == kind,
                Artifact.status.in_(["ACTIVE", "LOCKED"]))):
            item.status = "STALE"
            stale(service.db, service.user, [item.id])


def decide(service, workspace, request: DecisionRequest, request_id):
    from career.portfolio import plan

    ws = service.ws(workspace)
    service.editable(ws)
    previous, request_hash = _replay(service, workspace, "", "MaterialDecision", request_id, request)
    if previous:
        return previous
    current = preview(service, workspace)
    state = inputs(service, workspace)
    proposal = service.artifact(workspace, "JointPortfolioProposal")
    if (request.expected_revision != current["decision_revision"] or proposal.id != request.proposal_id
            or proposal.version != request.proposal_version or not _current(service, state, proposal)):
        raise ValueError("제안·문항·가이드·근거 버전이 바뀌었습니다. 현재 제안을 다시 확인해 주세요.")
    accepted = request.disposition in ACCEPTED
    candidates = {p["candidate_id"]: p for p in proposal.data["personas"]}
    if len(set(request.persona_candidate_ids)) != len(request.persona_candidate_ids) or not set(request.persona_candidate_ids) <= candidates.keys():
        raise ValueError("현재 제안의 Persona 후보 ID를 선택해 주세요.")
    if request.disposition == "ACCEPT" and (len(request.persona_candidate_ids) != 1 or request.items or request.persona_text):
        raise ValueError("원안 선택에는 Persona 후보 한 개만 지정해 주세요. 수정은 수정·혼합·직접 작성으로 저장하세요.")
    if request.disposition == "COMBINE" and len(request.persona_candidate_ids) < 2:
        raise ValueError("혼합할 Persona 후보를 두 개 이상 선택해 주세요.")
    items = tuple(Material.model_validate(i) for i in proposal.data["items"]) if request.disposition == "ACCEPT" else request.items
    persona_text = (request.persona_text.strip() or " / ".join(candidates[i]["text"] for i in request.persona_candidate_ids)).strip()
    if accepted:
        if state["holds"] or not persona_text or (proposal.data["needs_user_edit"] and request.disposition == "ACCEPT"):
            raise ValueError("오프라인 작성표의 소재·메시지와 Persona를 직접 검토·수정해 주세요.")
        _validate_materials(state, items, complete=True)
        if any("정해 주세요" in i.climax or "작성해 주세요" in i.primary_message for i in items):
            raise ValueError("작성표의 안내 문구를 실제 문항 메시지·핵심 장면으로 바꿔 주세요.")
    elif request.items or request.persona_text or request.persona_candidate_ids or not request.reason.strip():
        raise ValueError("거절·보류에는 이유만 남겨 주세요. 선택이나 승인으로 저장하지 않습니다.")
    accepted_ids = sorted({ident for item in items for ident in item.evidence_ids}) if accepted else []
    proposed_ids = {ident for item in proposal.data["items"] for ident in item["evidence_ids"]}
    refused = sorted(proposed_ids - set(accepted_ids)) if accepted or request.disposition == "REJECT" else []
    event = {"input_revision": state["input_revision"], "proposal_id": proposal.id, "proposal_version": proposal.version,
             "disposition": request.disposition, "reason": request.reason, "actor_id": service.user,
             "is_selection": accepted,
             "selected_evidence_ids": accepted_ids, "refused_evidence_ids": refused,
             "unselected_evidence_ids": sorted({c["evidence_id"] for c in state["candidates"]} - set(accepted_ids)),
             "request_id": request_id, "request_hash": request_hash, "claim_approval_granted": False}
    _invalidate(service, workspace)
    persona, _ = save(service.db, service.user, workspace, "PersonaDecision", {
        **event, "candidate_ids": list(request.persona_candidate_ids), "text": persona_text if accepted else "",
        "requires_strategy_approval": accepted}, deps=[proposal.id], sources=state["source_ids"])
    decision, _ = save(service.db, service.user, workspace, "MaterialDecision", {
        **event, "persona_decision_id": persona.id, "items": [i.model_dump(mode="json") for i in items] if accepted else []},
        deps=[proposal.id, persona.id], sources=state["source_ids"])
    if accepted:
        portfolio = plan(service, workspace, {"items": [{"question_id": i.question_id,
            "evaluation_intent": state["guides"][i.question_id]["guide"]["question_intent"],
            "identity_role": i.identity_role, "primary_message_candidates": [i.primary_message],
            "evidence_candidate_ids": list(i.evidence_ids),
            "avoided_repetition": ["수치·메시지·핵심 장면 중복 확인", "의미가 겹치는지는 최종 전체 검수에서 다시 확인"]} for i in items]},
            _joint_decision=decision)
        portfolio.data = {**portfolio.data, "material_decision_id": decision.id}
        ws.state = "WAITING_STRATEGY_APPROVAL"
    else:
        ws.state = "NEED_USER_ACTION"
    return decision


def require_decision(service, workspace, *, approved=True, portfolio=False):
    decision = _decision(service, workspace)
    if decision is None:
        return None
    state = inputs(service, workspace)
    if not _current(service, state, decision) or decision.data["disposition"] not in ACCEPTED or state["holds"]:
        raise ValueError("현재 소재·Persona 선택을 확인해 주세요. 보류·거절·낡은 선택으로 작성할 수 없습니다.")
    persona = service.artifact(workspace, "PersonaDecision")
    if persona.id != decision.data["persona_decision_id"] or (approved and persona.status != "LOCKED"):
        raise ValueError("선택한 Persona를 기존 지원 전략과 함께 확인하고 전략을 다시 승인해 주세요.")
    _validate_materials(state, tuple(Material.model_validate(i) for i in decision.data["items"]), complete=True)
    if portfolio:
        allocation = service.artifact(workspace, "QuestionPortfolio")
        if allocation.status != "LOCKED" or decision.id not in allocation.depends_on:
            raise ValueError("소재 선택을 반영한 모든 문항의 역할 배분을 별도로 승인해 주세요.")
    return decision


def approve_persona(service, workspace):
    decision = _decision(service, workspace)
    if decision and decision.status in {"ACTIVE", "LOCKED"}:
        require_decision(service, workspace, approved=False)
        persona = service.artifact(workspace, "PersonaDecision")
        lock(service.db, service.user, persona)


def hint(service, workspace, qid):
    decision = _decision(service, workspace)
    if decision is None:
        return {}, []
    try:
        require_decision(service, workspace, approved=False)
        persona = service.artifact(workspace, "PersonaDecision")
        portfolio = latest(service.db, service.user, workspace, "QuestionPortfolio", required=False)
        material = next(i for i in decision.data["items"] if i["question_id"] == qid)
        return {"current": True, "decision_id": decision.id, "version": decision.version,
                "persona_id": persona.id, "persona_text": persona.data["text"], "material": material,
                "approvals_ready": persona.status == "LOCKED" and bool(portfolio and portfolio.status == "LOCKED"
                    and decision.id in portfolio.depends_on), "fact_authority": False}, [decision.id, persona.id]
    except (ValueError, LookupError, StopIteration):
        return {"current": False, "notice": "소재·Persona 선택을 현재 문항·근거로 다시 확인해 주세요."}, []
