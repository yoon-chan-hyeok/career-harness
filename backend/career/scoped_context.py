"""I02 read-only context projection. No provider, writes, embeddings or approval authority."""

from copy import deepcopy
from typing import Annotated, Any, Literal

from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from career.artifacts import fresh, latest
from career.entities import WritingRuleRecord
from career.experience_options import usable_ownership
from career.models import Evidence, Fact, Source, Workspace
from career.promotion import usable_rule
from career.question_contracts import Contract
from career.token_estimation import gpt_oss_input_tokens
from career.truth import canonical, owned
from career.v3_contracts import Digest, Identifier
from career.v3_preview import RECORD_TYPES, _read_only, digest, experience_card
from career.validation import GOOD

TaskType = Literal["EXPERIENCE_REVIEW", "JOB_ASSESS", "QUESTION_PORTFOLIO", "COVER_WRITE", "RESUME_WRITE"]
VERSION = "scoped-context-i02-v1"
WRITING_TASKS = {"QUESTION_PORTFOLIO", "COVER_WRITE", "RESUME_WRITE"}


class ContextRequest(Contract):
    task_type: TaskType
    application_id: Identifier | None = None
    question_id: Identifier | None = None
    required_evidence_ids: tuple[Identifier, ...] = Field(default=(), max_length=20)
    required_fact_ids: tuple[Identifier, ...] = Field(default=(), max_length=20)
    expected_revisions: dict[Identifier, Digest] = Field(default_factory=dict, max_length=150)
    approved_rule_pack_version: Identifier | None = None
    max_input_tokens: Annotated[int, Field(strict=True, ge=1, le=32768)] = 8192
    # I02 has no transfer endpoint. This field cannot grant future provider consent.
    external_transfer_consent: Literal[False] = False

    @model_validator(mode="after")
    def task_scope(self):
        if self.task_type == "EXPERIENCE_REVIEW":
            if self.application_id or self.question_id or self.required_fact_ids:
                raise ValueError("경험 조회에는 지원·문항·프로필 사실 범위를 섞을 수 없습니다.")
        elif not self.application_id:
            raise ValueError("이 작업의 지원 범위가 필요합니다.")
        if (self.task_type == "COVER_WRITE") != bool(self.question_id):
            raise ValueError("자소서 작성 문항은 COVER_WRITE에서만 지정해 주세요.")
        if self.required_fact_ids and self.task_type not in {"JOB_ASSESS", "RESUME_WRITE"}:
            raise ValueError("이 작업에는 프로필 사실을 포함하지 않습니다.")
        for values in (self.required_evidence_ids, self.required_fact_ids):
            if len(values) != len(set(values)):
                raise ValueError("같은 필수 자료를 중복 지정할 수 없습니다.")
        return self


class ContextReference(Contract):
    kind: Identifier
    id: Identifier
    revision: Digest
    version: int | None = None
    status: Identifier


class ScopedContextManifest(Contract):
    contract_version: Literal["scoped-context-i02-v1"] = VERSION
    namespace: Literal["USER_PRIVATE_CONTEXT"] = "USER_PRIVATE_CONTEXT"
    owner_id: Identifier
    task_type: TaskType
    application_id: Identifier | None
    question_id: Identifier | None
    required_evidence_ids: tuple[Identifier, ...]
    required_fact_ids: tuple[Identifier, ...]
    requested_rule_pack_version: Identifier | None
    references: tuple[ContextReference, ...]
    missing_information: tuple[str, ...]
    revision: Digest
    estimated_input_tokens: int
    max_input_tokens: int
    budget_status: Literal["WITHIN_OFFLINE_ESTIMATE", "EXCEEDED"]
    estimation_method: Literal["OFFLINE_GPT_OSS_BPE_WITH_MARGIN_NOT_PROVIDER_USAGE"] = (
        "OFFLINE_GPT_OSS_BPE_WITH_MARGIN_NOT_PROVIDER_USAGE")
    rule_pack_status: Literal["LEGACY_UNCHANGED_NOT_RESOLVED", "REQUESTED_VERSION_UNRESOLVED"]
    consent_status: Literal["NOT_EVALUATED_NO_EXTERNAL_TRANSFER"] = "NOT_EVALUATED_NO_EXTERNAL_TRANSFER"
    model_ref: None = None
    prompt_ref: None = None
    external_transfer_allowed: Literal[False] = False


class ContextPack(Contract):
    mode: Literal["READ_ONLY_OFFLINE_PREVIEW"] = "READ_ONLY_OFFLINE_PREVIEW"
    status: Literal["INPUT_READY_OFFLINE", "HOLD"]
    manifest: ScopedContextManifest
    payload: dict[str, Any] | None
    can_execute: Literal[False] = False
    completion_proof: Literal[False] = False


def compile_task_context(db: Session, authenticated_user_id: str, request: ContextRequest) -> ContextPack:
    """Authenticated caller supplies the actor separately; request has no user_id field."""
    _read_only(db)
    refs: dict[str, ContextReference] = {}
    missing: list[str] = []
    payload: dict[str, Any] = {"task_type": request.task_type}

    def reference(kind, row):
        values = {column.name: getattr(row, column.name) for column in row.__table__.columns}
        ref = ContextReference(kind=kind, id=row.id, revision=digest(values),
                               version=getattr(row, "version", None),
                               status=getattr(row, "status", getattr(row, "state", "CURRENT")))
        refs[f"{kind}:{row.id}"] = ref
        return ref

    workspace = owned(db, Workspace, authenticated_user_id, request.application_id) if request.application_id else None
    question = None
    if workspace:
        reference("APPLICATION", workspace)
        payload["application"] = {"id": workspace.id, "company": workspace.company,
                                  "role": workspace.role, "jd_raw": workspace.jd_raw}
        if request.question_id:
            question = next((q for q in workspace.data.get("questions", []) if q["id"] == request.question_id), None)
            if question is None:
                raise LookupError("찾을 수 없는 문항입니다.")
            refs[f"QUESTION:{question['id']}"] = ContextReference(
                kind="QUESTION", id=question["id"], revision=digest(question), status="CURRENT")
            payload["question"] = deepcopy(question)
        elif request.task_type == "QUESTION_PORTFOLIO":
            payload["questions"] = deepcopy(workspace.data.get("questions", []))
            if not payload["questions"]:
                missing.append("CURRENT_QUESTIONS_REQUIRED")

    # Scope is validated before any personal content is included. No global search/embedding occurs.
    evidence_rows = [owned(db, Evidence, authenticated_user_id, ident) for ident in request.required_evidence_ids]
    fact_rows = [owned(db, Fact, authenticated_user_id, ident) for ident in request.required_fact_ids]
    evidence_sources = {row.id: owned(db, Source, authenticated_user_id, row.source_id) for row in evidence_rows}
    fact_sources = {row.id: owned(db, Source, authenticated_user_id, row.source_id) for row in fact_rows}
    for row in evidence_rows:
        if row.kind == "EXPRESSION" or evidence_sources[row.id].authority == "REFERENCE":
            raise ValueError("표현·가이드 자료를 필수 경험 사실로 사용할 수 없습니다.")

    if workspace and request.task_type in WRITING_TASKS:
        if workspace.state in {"SUBMISSION_FROZEN", "SUBMITTED", "CLOSED"}:
            missing.append("APPLICATION_FROZEN_OR_CLOSED")
        pack = latest(db, authenticated_user_id, workspace.id, "EvidencePack", required=False)
        allowed = set()
        if pack:
            reference("ARTIFACT", pack)
            try:
                fresh(db, authenticated_user_id, pack)
                allowed = {item["evidence_id"] for item in pack.data.get("items", [])
                           if item.get("classification") in {"DIRECT", "ADJACENT"}}
            except (ValueError, LookupError):
                missing.append("CURRENT_EVIDENCE_PACK_REQUIRED")
        else:
            missing.append("CURRENT_EVIDENCE_PACK_REQUIRED")
        if set(request.required_evidence_ids) - allowed:
            missing.append("EVIDENCE_OUTSIDE_CURRENT_APPLICATION_PACK")
        strategy = latest(db, authenticated_user_id, workspace.id, "ApplicationBrief", required=False)
        if strategy:
            reference("ARTIFACT", strategy)
        try:
            if strategy is None or strategy.status != "LOCKED":
                raise ValueError()
            fresh(db, authenticated_user_id, strategy)
            payload["strategy"] = {key: deepcopy(strategy.data[key]) for key in (
                "positioning", "base_profession_identity", "main_skill_message", "differentiator_message",
                "assignment_statement", "fatal_gaps", "selection_risks", "do_not_position_as") if key in strategy.data}
        except (ValueError, LookupError):
            missing.append("CURRENT_APPROVED_STRATEGY_REQUIRED")
        if question:
            brief = latest(db, authenticated_user_id, workspace.id, "QuestionBrief", question["id"], required=False)
            if brief:
                reference("ARTIFACT", brief)
            try:
                if brief is None:
                    raise ValueError()
                fresh(db, authenticated_user_id, brief)
                if set(brief.data.get("evidence_ids", [])) != set(request.required_evidence_ids):
                    raise ValueError()
            except (ValueError, LookupError):
                missing.append("CURRENT_QUESTION_EVIDENCE_SCOPE_REQUIRED")

    if request.task_type != "JOB_ASSESS" and not request.required_evidence_ids:
        missing.append("REQUIRED_EVIDENCE_NOT_SELECTED")
    payload["experiences"] = []
    for row in evidence_rows:
        source = evidence_sources[row.id]
        reference("EVIDENCE", row)
        reference("SOURCE", source)
        card = experience_card(db, authenticated_user_id, row.id)
        if request.task_type != "EXPERIENCE_REVIEW" and (card.warnings or not usable_ownership(row)):
            missing.append("CURRENT_VERIFIED_EXPERIENCE_AND_OWNERSHIP_REQUIRED")
        experience = {"id": row.id, "revision": card.revision, "title": row.title,
                      "body": row.body, "status": row.status, "warnings": list(card.warnings), "records": []}
        for kind, model in RECORD_TYPES:
            for item in db.scalars(select(model).where(model.user_id == authenticated_user_id,
                    model.evidence_id == row.id, model.status.not_in(["SUPERSEDED", "DO_NOT_USE"])).order_by(model.id)):
                reference(kind, item)
                linked = owned(db, Source, authenticated_user_id, item.source_id) if item.source_id else None
                if linked:
                    reference("SOURCE", linked)
                if item.status in GOOD and linked and linked.status in GOOD and linked.authority != "REFERENCE":
                    experience["records"].append({"id": item.id, "kind": kind, "data": deepcopy(item.data)})
                elif request.task_type != "EXPERIENCE_REVIEW":
                    missing.append("LINKED_TRUTH_REQUIRES_REVIEW")
        payload["experiences"].append(experience)

    current_facts = {row["id"] for row in canonical(db, authenticated_user_id).values()} if fact_rows else set()
    payload["profile_facts"] = []
    for row in fact_rows:
        source = fact_sources[row.id]
        reference("FACT", row)
        reference("SOURCE", source)
        if row.id not in current_facts or source.status not in GOOD or source.authority == "REFERENCE":
            missing.append("CURRENT_CANONICAL_FACT_REQUIRED")
        else:
            payload["profile_facts"].append({"id": row.id, "key": row.key, "value": deepcopy(row.value)})

    # Voice is projected only from explicit, still-valid scoped user directives.
    # Learned rules/Persona/9-book policy execution stay with their later phases.
    payload["preferences"] = []
    if workspace and request.task_type in WRITING_TASKS:
        scopes = {"USER": {authenticated_user_id}, "COMPANY": {workspace.company}, "ROLE_TYPE": {workspace.role},
                  "PROJECT": {row.title for row in evidence_rows}, "INDUSTRY": {workspace.data.get("industry")}}
        domain = "RESUME" if request.task_type == "RESUME_WRITE" else "COVER"
        if question:
            from career.writing_plans import family

            scopes["QUESTION_TYPE"] = {family(question["text"])}
        for row in db.scalars(select(WritingRuleRecord).where(WritingRuleRecord.user_id == authenticated_user_id,
                WritingRuleRecord.status.in_(["CANONICAL", "VERIFIED"])).order_by(WritingRuleRecord.id)):
            data = row.data
            if (data.get("origin") != "USER_DIRECTIVE" or data.get("domain", "COMMON") not in {"COMMON", domain}
                    or data.get("scope_value") not in scopes.get(data.get("scope_type", ""), set()) or not row.source_id):
                continue
            source = owned(db, Source, authenticated_user_id, row.source_id)
            if source.status not in GOOD or not usable_rule(db, authenticated_user_id, data):
                continue
            reference("PREFERENCE", row)
            reference("SOURCE", source)
            payload["preferences"].append({"id": row.id, "rule": data["rule"],
                                            "authority": "EXPLICIT_PREFERENCE_NOT_FACT"})

    rule_status = "REQUESTED_VERSION_UNRESOLVED" if request.approved_rule_pack_version else "LEGACY_UNCHANGED_NOT_RESOLVED"
    if request.approved_rule_pack_version:
        missing.append("APPROVED_RULE_PACK_VERSION_NOT_RESOLVED_IN_I02")
    for key, expected in request.expected_revisions.items():
        if key not in refs or refs[key].revision != expected:
            raise ValueError("문맥 자료의 버전이 바뀌었거나 현재 범위를 벗어났습니다. 다시 조회해 주세요.")
    # The budget covers every required payload item. No silent truncation/partial context.
    estimate = gpt_oss_input_tokens(payload)
    exceeded = estimate > request.max_input_tokens
    if exceeded:
        missing.append("INPUT_BUDGET_EXCEEDED_NO_TRUNCATION")
    ordered = tuple(refs[key] for key in sorted(refs))
    reasons = tuple(sorted(set(missing)))
    revision = digest([authenticated_user_id, request.model_dump(mode="json"),
                       [ref.model_dump() for ref in ordered], payload, reasons, VERSION])
    manifest = ScopedContextManifest(owner_id=authenticated_user_id, task_type=request.task_type,
        application_id=request.application_id, question_id=request.question_id,
        required_evidence_ids=request.required_evidence_ids, required_fact_ids=request.required_fact_ids,
        requested_rule_pack_version=request.approved_rule_pack_version, references=ordered,
        missing_information=reasons, revision=revision, estimated_input_tokens=estimate,
        max_input_tokens=request.max_input_tokens, budget_status="EXCEEDED" if exceeded else "WITHIN_OFFLINE_ESTIMATE",
        rule_pack_status=rule_status)
    return ContextPack(status="HOLD" if reasons else "INPUT_READY_OFFLINE", manifest=manifest,
                       payload=None if reasons else payload)
