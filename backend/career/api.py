import hashlib
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from career.authentication import authenticate, public_auth_configuration
from career.conversation import ChatRequest, conversation_uses_ai, converse, history
from career.db import Record, SessionLocal, engine
from career.entities import ENTITY_MODELS
from career.extraction import ExtractionDecision, ExtractionRequest
from career.models import (
    AIUsageBucket,
    AIUsageReservation,
    AIUsageSettings,
    Artifact,
    Evidence,
    ExecutionRun,
    Fact,
    Feedback,
    PromptRun,
    RequestRateBucket,
    Revision,
    ServiceMember,
    Source,
    Workspace,
)
from career.production import install_security, readiness, validate_runtime_settings
from career.projections import APPLICATION_MODELS, CorrectionRecord
from career.provider_config import (
    ProviderCheckRequest,
    ProviderConfigRequest,
    configure_provider,
    note_verification,
    provider_available,
    provider_settings,
    provider_status,
    require_local_owner,
)
from career.provider_policy import BudgetExceeded
from career.providers import ProviderUnavailable
from career.public_guard import bind_request, limit_request
from career.retrieval import configured_embedder, index_embeddings, search
from career.semantic_models import LocalEvidenceEmbedding
from career.telemetry import export_events
from career.truth import (
    add_evidence,
    canonical,
    import_corpus,
    invalidate_source,
    owned,
    register_source,
    view,
)
from career.upgrade_models import EditorDraft
from career.usage_limits import request_budget_scope
from career.workflow import Workflow


@asynccontextmanager
async def lifespan(_app: FastAPI):
    validate_runtime_settings()
    yield


app = FastAPI(title="Career Harness", version="0.1.0", lifespan=lifespan)
install_security(app)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, error: RequestValidationError):
    if request.url.path.startswith("/api/account/delete"):
        return JSONResponse(status_code=422, content={"detail": "계정 삭제 확인과 본인 인증을 확인해 주세요."})
    if request.url.path.startswith("/api/providers"):
        # FastAPI's normal error includes the invalid input; this route may carry a key.
        return JSONResponse(status_code=422, content={"detail": "AI 제공자 입력 형식과 무료 사용 확인을 확인해 주세요."})
    if request.url.path.startswith(("/api/sources/upload", "/api/editor-drafts", "/api/semantic/")):
        return JSONResponse(status_code=422, content={"detail": "입력 형식·크기·필수 항목을 확인해 주세요."})
    return await request_validation_exception_handler(request, error)


def database(request: Request):
    with SessionLocal() as session:
        session.info["career_request_method"] = request.method
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


def identity_only(authorization: Annotated[str | None, Header()] = None,
                  db: Session = Depends(database, scope="function")) -> str:
    ident = authenticate(authorization)
    limit_request(db.get_bind(), ident, db.info.get("career_request_method", "GET"))
    return ident


def identity_member(authorization: Annotated[str | None, Header()] = None,
                    db: Session = Depends(database, scope="function")) -> str:
    from career.public_service import ensure_public_member
    from career.service_access import require_member, shared_service

    ident = identity_only(authorization, db)
    if shared_service() or ident.startswith("__career_"):
        # Release the access read before the independent AI reservation transaction.
        with Session(db.get_bind()) as access:
            ensure_public_member(access, ident, authorization)
            require_member(access, ident)
            access.commit()
    bind_request(db, ident)
    return ident


def user(authorization: Annotated[str | None, Header()] = None,
         db: Session = Depends(database, scope="function")) -> str:
    from career.public_service import require_public_consent

    ident = identity_member(authorization, db)
    with Session(db.get_bind()) as access:
        require_public_consent(access, ident)
    return ident


DB = Annotated[Session, Depends(database, scope="function")]
User = Annotated[str, Depends(user)]
MemberUser = Annotated[str, Depends(identity_member)]


@app.exception_handler(ValueError)
async def value_error(_request: Request, error: ValueError):
    return JSONResponse(status_code=409, content={"detail": str(error)})


@app.exception_handler(LookupError)
async def lookup_error(_request: Request, _error: LookupError):
    return JSONResponse(status_code=404, content={"detail": "항목을 찾을 수 없습니다."})


@app.exception_handler(ProviderUnavailable)
@app.exception_handler(BudgetExceeded)
async def provider_error(_request: Request, error: ProviderUnavailable):
    return JSONResponse(status_code=503, content={"detail": str(error)})


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready_health():
    code, payload = readiness(engine)
    return JSONResponse(status_code=code, content=payload)


@app.get("/api/auth/config")
def auth_config():
    return public_auth_configuration()


@app.get("/api/settings")
def settings(db: DB, ident: MemberUser):
    return {
        "user": ident,
        "ai_available": provider_available(),
        "research": "manual_and_optional_live",
        "semantic_search": {"device_available": True, "device_model_enabled_by_default": False,
                            "server_embeddings_configured": configured_embedder(db) is not None},
    }


@app.get("/api/providers")
def providers_status(ident: User):
    return provider_status(ident)


@app.post("/api/providers/configure")
def providers_configure(body: ProviderConfigRequest, ident: User):
    return configure_provider(ident, body)


class ProviderCheckMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=80)

    @field_validator("message")
    @classmethod
    def korean_message(cls, value: str) -> str:
        if not any("가" <= char <= "힣" for char in value):
            raise ValueError("A short Korean message is required")
        return value


@app.post("/api/providers/check")
def providers_check(_body: ProviderCheckRequest, db: DB, ident: User):
    from career.providers import configured_provider

    require_local_owner(ident)
    snapshot = provider_settings()
    if snapshot.provider not in {"huggingface", "groq"}:
        raise HTTPException(503, "무료 연결 확인에는 Hugging Face 또는 Groq를 선택해 주세요.")
    if not provider_available():
        raise HTTPException(503, "제공자와 키, 모델, 무료 사용 확인을 먼저 설정해 주세요.")
    with request_budget_scope(db, ident, "provider_check"):
        return _provider_probe(ident, snapshot, configured_provider)


def _provider_probe(ident, snapshot, configured_provider):
    try:
        # This explicit probe sends synthetic text only, never personal application data.
        result = configured_provider().structured(
            "provider_connection_check",
            {"task": "Return one brief Korean greeting in message. Do not include any credentials or configuration."},
            ProviderCheckMessage,
        )
        ProviderCheckMessage.model_validate(result)
        note_verification(True, expected=snapshot)
    except Exception:
        # Do not forward provider errors or output: either may echo a credential.
        note_verification(False, expected=snapshot)
        return {**provider_status(ident), "message": "연결을 확인하지 못했습니다. 키 권한·무료 사용 범위·모델 설정을 확인해 주세요."}
    status = provider_status(ident)
    message = "실제 요청으로 연결을 확인했습니다." if status["live_verified"] else "설정이 바뀌었습니다. 현재 설정으로 다시 확인해 주세요."
    return {**status, "message": message}


class CreateWorkspace(BaseModel):
    company: str = Field(min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=200)
    jd_raw: str = Field(min_length=1, max_length=100000)
    mode: str = "GUIDED"


@app.post("/api/opportunities")
@app.post("/api/applications")
def create_workspace(body: CreateWorkspace, db: DB, ident: User):
    return view(Workflow(db, ident).create(body.company, body.role, body.jd_raw, body.mode))


@app.get("/api/applications")
def workspaces(db: DB, ident: User):
    return [
        view(w)
        for w in db.scalars(
            select(Workspace).where(Workspace.user_id == ident).order_by(Workspace.created_at.desc())
        )
    ]


@app.get("/api/opportunities/rankings")
def opportunity_rankings(db: DB, ident: User):
    from career.assessment import rankings

    return rankings(db, ident)


@app.get("/api/applications/{workspace}")
def workspace_detail(workspace: str, db: DB, ident: User):
    ws = owned(db, Workspace, ident, workspace)
    artifacts = [
        view(a)
        for a in db.scalars(
            select(Artifact)
            .where(Artifact.workspace_id == workspace, Artifact.user_id == ident)
            .order_by(Artifact.created_at)
        )
    ]
    return {**view(ws), "artifacts": artifacts}


@app.get("/api/profile")
def profile(db: DB, ident: User):
    return canonical(db, ident)


@app.get("/api/rules/candidates")
def rule_candidates(db: DB, ident: User):
    from career.promotion import list_candidates

    return list_candidates(db, ident)


@app.get("/api/rules/correction-cases")
def rule_corrections(db: DB, ident: User):
    from career.promotion import correction_cases

    return correction_cases(db, ident)


class RuleCandidateRequest(BaseModel):
    source_case_ids: list[str] = Field(min_length=2, max_length=20)
    confirmed_external_eval: bool = False


@app.post("/api/rules/candidates/propose")
def rule_propose(body: RuleCandidateRequest, db: DB, ident: User):
    from career.promotion import propose_from_corrections

    with request_budget_scope(db, ident, "rule_candidate"):
        return propose_from_corrections(
            db, ident, body.source_case_ids, confirmed_external_eval=body.confirmed_external_eval
        )


class RuleEvaluationRequest(BaseModel):
    confirmed_external_eval: bool = False


@app.post("/api/rules/candidates/{candidate_id}/evaluate")
def rule_evaluate(candidate_id: str, body: RuleEvaluationRequest, db: DB, ident: User):
    from career.promotion import evaluate_candidate

    with request_budget_scope(db, ident, "rule_evaluation"):
        return evaluate_candidate(db, ident, candidate_id, confirmed_external_eval=body.confirmed_external_eval)


@app.get("/api/rules/evaluations/{evaluation_id}")
def rule_evaluation(evaluation_id: str, db: DB, ident: User):
    row = owned(db, Record, ident, evaluation_id)
    if row.kind != "RuleEvaluation":
        raise LookupError("평가 기록을 찾을 수 없습니다.")
    return view(row)


class RulePromotionRequest(BaseModel):
    evaluation_id: str
    confirmed: bool = False


@app.post("/api/rules/candidates/{candidate_id}/promote")
def rule_promote(candidate_id: str, body: RulePromotionRequest, db: DB, ident: User):
    from career.promotion import promote_candidate

    return promote_candidate(db, ident, candidate_id, body.evaluation_id, body.confirmed)


class DirectPreferenceRequest(BaseModel):
    rule: str = Field(min_length=1, max_length=10000)
    scope_type: Literal["USER", "COMPANY", "ROLE_TYPE", "QUESTION_TYPE", "PROJECT", "INDUSTRY"] = "USER"
    scope_value: str = ""
    domain: Literal["COMMON", "COVER", "RESUME", "OPPORTUNITY"] = "COMMON"
    confirmed: bool = False


@app.post("/api/rules/preferences")
def rule_preference(body: DirectPreferenceRequest, db: DB, ident: User):
    from career.promotion import direct_preference

    return direct_preference(db, ident, **body.model_dump())


@app.get("/api/fact-conflicts")
def fact_conflicts(db: DB, ident: User):
    return [
        {**view(f), "source_title": owned(db, Source, ident, f.source_id).path}
        for f in db.scalars(select(Fact).where(Fact.user_id == ident, Fact.status == "CONFLICTED"))
    ]


@app.post("/api/fact-conflicts/{fact_id}/resolve")
def fact_conflict_decision(fact_id: str, body: dict[str, Any], db: DB, ident: User):
    from career.truth import resolve_fact_conflict

    return resolve_fact_conflict(db, ident, fact_id, body.get("confirmed") is True)


@app.post("/api/evidence/{evidence_id}/extract")
def extraction_proposal(evidence_id: str, body: ExtractionRequest, db: DB, ident: User):
    from career.extraction import propose

    if body.manual:
        return propose(Workflow(db, ident), evidence_id, body.manual.model_dump())
    with request_budget_scope(db, ident, "truth_extraction"):
        return propose(Workflow(db, ident), evidence_id)


@app.post("/api/extractions/{proposal_id}/apply")
def extraction_apply(proposal_id: str, body: ExtractionDecision, db: DB, ident: User):
    from career.extraction import apply

    return {
        "entity_ids": apply(
            Workflow(db, ident),
            proposal_id,
            body.confirmed,
            [s.model_dump() for s in body.selections] if body.selections is not None else None,
            body.decision,
        )
    }


@app.get("/api/references")
def reference_list(db: DB, ident: User):
    from career.references import listing

    return listing(db, ident)


@app.get("/api/resume-master")
def resume_master(db: DB, ident: User):
    from career.resume_master import current_master

    item = current_master(Workflow(db, ident))
    return view(item) if item else None


@app.get("/api/expressions")
def expressions(db: DB, ident: User):
    from career.expressions import listing

    return listing(Workflow(db, ident))


@app.patch("/api/expressions/{expression_id}")
def expression_use(expression_id: str, body: dict[str, Any], db: DB, ident: User):
    from career.expressions import set_active

    active = body.get("active")
    if type(active) is not bool:
        raise ValueError("표현 사용 여부를 선택해 주세요.")
    return view(set_active(Workflow(db, ident), expression_id, active))


@app.post("/api/resume-master")
def set_resume_master(body: dict[str, Any], db: DB, ident: User):
    from career.resume_master import save_master

    if body.get("confirmed") is not True:
        raise ValueError("마스터로 재사용할 이력서를 직접 확인해 주세요.")
    return view(save_master(Workflow(db, ident), body["artifact_id"]))


@app.post("/api/applications/{workspace}/resume/file-qa")
def resume_file_qa(workspace: str, body: dict[str, Any], db: DB, ident: User):
    from career.resume_master import confirm_file_qa

    return view(confirm_file_qa(Workflow(db, ident), workspace, body["artifact_id"], body.get("confirmed")))


@app.get("/api/references/{reference_id}")
def reference_content(reference_id: str, db: DB, ident: User):
    record = owned(db, Record, ident, reference_id)
    if record.kind != "SupplementReference":
        raise LookupError("추가 자료가 아닙니다.")
    return view(record)


@app.post("/api/references/{reference_id}/activation")
def reference_activation(reference_id: str, body: dict[str, Any], db: DB, ident: User):
    from career.references import activate

    if not isinstance(body.get("active"), bool):
        raise ValueError("자료 사용 여부를 선택해 주세요.")
    return activate(db, ident, reference_id, body["active"])


@app.get("/api/applications/{workspace}/revision-proposals")
def revision_proposals(workspace: str, db: DB, ident: User):
    from career.human_review import proposals

    return proposals(Workflow(db, ident), workspace)


@app.post("/api/applications/{workspace}/revision-proposals/{proposal_id}")
def revision_decision(workspace: str, proposal_id: str, body: dict[str, Any], db: DB, ident: User):
    from career.human_review import resolve

    if body.get("new_text") is not None and not isinstance(body["new_text"], str):
        raise ValueError("수정 문장을 입력해 주세요.")
    return resolve(Workflow(db, ident), workspace, proposal_id, body.get("decision"), body.get("new_text"))


@app.get("/api/applications/{workspace}/conversation")
def conversation_history(workspace: str, db: DB, ident: User):
    return history(Workflow(db, ident), workspace)


@app.post("/api/applications/{workspace}/conversation")
def conversation_send(workspace: str, body: ChatRequest, db: DB, ident: User):
    from career.activity import run_operation

    service = Workflow(db, ident)
    past = history(service, workspace)
    if any(t["data"]["request"]["client_id"] == body.client_id for t in past):
        return converse(service, workspace, body)
    ws = service.ws(workspace)
    selected_kind = None
    if body.artifact_id:
        selected_kind = owned(db, Artifact, ident, body.artifact_id).kind
    return run_operation(db, ident, workspace, "conversation", lambda: converse(service, workspace, body),
                         uses_ai=conversation_uses_ai(body, ws.state, selected_kind))


@app.get("/api/applications/{workspace}/activity")
def workspace_activity(workspace: str, db: DB, ident: User):
    from career.activity import snapshot

    return snapshot(db, ident, workspace)


@app.get("/api/applications/{workspace}/correction-proposals")
def correction_proposals(workspace: str, db: DB, ident: User):
    from career.structured_corrections import pending

    return pending(Workflow(db, ident), workspace)


class AnalysisCorrectionRequest(BaseModel):
    artifact_id: str
    old_fields: dict
    new_fields: dict
    reason: str = "직접 요청한 분석 교정"


@app.post("/api/applications/{workspace}/correction-proposals")
def correction_propose(workspace: str, body: AnalysisCorrectionRequest, db: DB, ident: User):
    from career.structured_corrections import propose

    return propose(Workflow(db, ident), workspace, **body.model_dump())


class AnalysisCorrectionDecision(BaseModel):
    confirmed: bool = False
    reject: bool = False


@app.post("/api/applications/{workspace}/correction-proposals/{proposal_id}")
def correction_apply(workspace: str, proposal_id: str, body: AnalysisCorrectionDecision, db: DB, ident: User):
    from career.activity import run_operation
    from career.structured_corrections import apply

    return run_operation(
        db,
        ident,
        workspace,
        "correct-analysis",
        lambda: apply(Workflow(db, ident), workspace, proposal_id, body.confirmed, body.reject),
    )


@app.get("/api/applications/{workspace}/resume/preview")
def resume_preview(workspace: str, db: DB, ident: User):
    from fastapi.responses import HTMLResponse

    from career.resume import HTMLRenderer, ResumeContent, legacy_sections

    item = Workflow(db, ident).artifact(workspace, "ResumeContent")
    content = ResumeContent.model_validate(
        {"sections": item.data["sections"]} if "sections" in item.data else legacy_sections(item.data)
    )
    return HTMLResponse(
        HTMLRenderer().render(content),
        headers={
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.post("/api/truth/{kind}")
def truth_entity(kind: str, body: dict[str, Any], db: DB, ident: User):
    from career.domain import save_entity

    return view(save_entity(db, ident, kind, body["data"], body.get("confirmed") is True))


@app.get("/api/truth/{kind}")
def truth_entities(kind: str, db: DB, ident: User):
    if kind not in ENTITY_MODELS:
        raise ValueError("지원하지 않는 근거 항목입니다.")
    model = ENTITY_MODELS[kind]
    return [view(row) for row in db.scalars(select(model).where(model.user_id == ident))]


@app.patch("/api/truth/{kind}/{entity_id}")
def patch_truth_entity(kind: str, entity_id: str, body: dict[str, Any], db: DB, ident: User):
    from career.domain import SCHEMAS, save_entity

    if kind not in ENTITY_MODELS:
        raise ValueError("지원하지 않는 근거 항목입니다.")
    previous = owned(db, ENTITY_MODELS[kind], ident, entity_id)
    data = {k: v for k, v in previous.data.items() if k in SCHEMAS[kind].model_fields}
    return view(save_entity(db, ident, kind, {**data, **body.get("data", {})}, body.get("confirmed") is True))


@app.get("/api/evidence")
@app.get("/api/projects")
def evidence_list(db: DB, ident: User):
    return [view(e) for e in db.scalars(select(Evidence).where(Evidence.user_id == ident))]


@app.get("/api/decision-graphs")
def graphs(db: DB, ident: User, q: str = "", intent: str = "ANY", limit: int = 20):
    from typing import cast

    from career.decision_graph import SearchIntent, search_graphs

    return search_graphs(db, ident, q, cast(SearchIntent, intent), limit)


@app.get("/api/decision-graphs/{graph_id}")
def graph_detail(graph_id: str, db: DB, ident: User):
    from career.decision_graph import graph_view

    return graph_view(db, ident, graph_id, include_stale=True)


class GraphConfirmation(BaseModel):
    confirmed: bool = False


@app.post("/api/decision-episodes/{episode_id}/graph")
def graph_project(episode_id: str, db: DB, ident: User):
    from career.decision_graph import project_episode

    return view(project_episode(db, ident, episode_id))


@app.post("/api/decision-graphs/{graph_id}/approval")
def graph_approval(graph_id: str, body: GraphConfirmation, db: DB, ident: User):
    from career.decision_graph import approve_graph

    return approve_graph(db, ident, graph_id, body.confirmed)


class GraphRelations(BaseModel):
    edges: list[dict]


@app.post("/api/decision-graphs/{graph_id}/relations")
def graph_relations(graph_id: str, body: GraphRelations, db: DB, ident: User):
    from career.decision_graph import EdgeProposal, add_relations

    return add_relations(db, ident, graph_id, [EdgeProposal.model_validate(edge) for edge in body.edges])


@app.get("/api/evidence/search")
def evidence_search(q: str, db: DB, ident: User, store="FACT"):
    embedder = configured_embedder(db)
    if embedder is None:
        return search(db, ident, q, store)
    with request_budget_scope(db, ident, "embedding_search"):
        try:
            return search(db, ident, q, store, embedder=embedder)
        except ProviderUnavailable:
            return search(db, ident, q, store)


@app.post("/api/evidence/index")
def reindex_evidence(db: DB, ident: User):
    embedder = configured_embedder(db)
    if embedder is None:
        raise ValueError(
            "의미 검색에는 PostgreSQL과 별도의 임베딩 제공자 설정이 필요합니다. 현재는 키워드 검색을 사용합니다."
        )
    with request_budget_scope(db, ident, "embedding_index"):
        return {"indexed": index_embeddings(db, ident, embedder)}


class NewEvidence(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=30000)
    source_title: str = Field(min_length=1, max_length=500)
    ownership: str = "UNKNOWN"
    forbidden_claims: list[str] = []
    confirmed: bool = False


@app.post("/api/evidence")
def create_evidence(body: NewEvidence, db: DB, ident: User):
    if body.ownership not in {
        "USER",
        "USER_AI_ASSISTED",
        "USER_MODIFIED_EXISTING_CODE",
        "TEAM",
        "LAB",
        "UNKNOWN",
    }:
        raise ValueError("올바른 수행 범위를 선택해 주세요.")
    source, _ = register_source(db, ident, "manual/" + body.source_title, body.body, "USER_CORRECTION")
    item = add_evidence(
        db,
        ident,
        source.id,
        body.title,
        body.body,
        {"ownership": {"implementation": body.ownership}, "forbidden_claims": body.forbidden_claims},
        "USER_CONFIRMED" if body.confirmed else "UNVERIFIED",
    )
    return view(item)


@app.post("/api/evidence/{evidence_id}/confirm")
def confirm_evidence(evidence_id: str, body: dict[str, Any], db: DB, ident: User):
    e = owned(db, Evidence, ident, evidence_id)
    if body.get("confirmed") is not True or e.kind == "EXPRESSION":
        raise ValueError("사실 근거를 직접 확인한 경우에만 승인할 수 있습니다.")
    if e.status == "CONFLICTED":
        raise ValueError("충돌한 근거는 정정된 새 근거로 교체해 주세요.")
    e.status = "USER_CONFIRMED"
    return view(e)


@app.post("/api/sources/import")
def source_import(db: DB, ident: User):
    require_local_owner(ident)
    return import_corpus(db, ident, Path(os.getenv("PRIVATE_INPUT_DIR", "private_input")))


@app.get("/api/sources")
def sources(db: DB, ident: User):
    result = []
    for source in db.scalars(select(Source).where(Source.user_id == ident)):
        item = view(source)
        if upload := item["data"].get("upload"):
            item["data"] = {**item["data"], "upload": {key: value for key, value in upload.items()
                                                     if key != "original_base64"}}
        result.append(item)
    return result


@app.delete("/api/sources/{source_id}")
def delete_source(source_id: str, db: DB, ident: User):
    source = owned(db, Source, ident, source_id)
    changed = invalidate_source(db, ident, source.id, delete_content=True)
    evidence_ids = (select(Evidence.id).join(Source, Source.id == Evidence.source_id)
                    .where(Evidence.user_id == ident, Source.user_id == ident, Source.status == "DO_NOT_USE"))
    db.execute(delete(LocalEvidenceEmbedding).where(LocalEvidenceEmbedding.user_id == ident,
                                                  LocalEvidenceEmbedding.evidence_id.in_(evidence_ids)))
    return {"stale_artifacts": changed, "historical_snapshots_preserved": True}


@app.get("/api/projects/{evidence_id}")
def project(evidence_id: str, db: DB, ident: User):
    return view(owned(db, Evidence, ident, evidence_id))


@app.post("/api/corrections")
def correction(body: dict[str, Any], db: DB, ident: User):
    from career.truth import add_fact

    source, _ = register_source(
        db, ident, "corrections/" + str(body["key"]), json.dumps(body, ensure_ascii=False), "USER_CORRECTION"
    )
    return view(add_fact(db, ident, source.id, body.get("fact_type", "profile"), body["key"], body["value"]))


@app.get("/api/applications/{workspace}/final-review-context")
def final_review_context(workspace: str, db: DB, ident: User):
    from career.final_decision import context

    return context(Workflow(db, ident), workspace)


@app.post("/api/applications/{workspace}/actions/{action}")
def action(
    workspace: str,
    action: str,
    body: dict[str, Any],
    db: DB,
    ident: User,
    idempotency_key: Annotated[str | None, Header()] = None,
):
    service = Workflow(db, ident)
    service.ws(workspace)
    digest = hashlib.sha256(json.dumps([action, body], sort_keys=True).encode()).hexdigest()
    if idempotency_key:
        for receipt in db.scalars(
            select(Record).where(Record.user_id == ident, Record.kind == "Idempotency")
        ):
            if receipt.data["key"] == idempotency_key and receipt.data["workspace"] == workspace:
                if receipt.data["digest"] != digest:
                    raise ValueError("같은 요청 키에 다른 내용이 전달되었습니다.")
                return receipt.data["result"]
    qid = body.get("qid", "")
    manual = body.get("manual")
    from career.assessment import assess, decide
    from career.expressions import approve as approve_expression
    from career.final_decision import confirm as final_review
    from career.portfolio import approve as approve_portfolio
    from career.portfolio import plan as plan_portfolio
    from career.research_workspace import collect as collect_research
    from career.research_workspace import decision as research_decision
    from career.research_workspace import extract as extract_research

    approval_kind = {
        "approve-strategy": "ApplicationBrief",
        "approve-question": "QuestionBrief",
        "claim-test": "QuestionBrief",
        "approve-portfolio": "QuestionPortfolio",
        "final-lock": "ResumeContent" if body.get("resume") else "Draft",
    }.get(action)
    operations = {
        "assess-opportunity": lambda: assess(service, workspace, manual),
        "decide-opportunity": lambda: decide(service, workspace, body["artifact_id"], body["decision"]),
        "research": lambda: service.research(workspace, body.get("live") is True, manual),
        "research-source": lambda: collect_research(service, workspace, body),
        "research-extract": lambda: extract_research(service, workspace, body.get("research_id"), manual),
        "research-confirm": lambda: research_decision(service, workspace, body),
        "expression-save": lambda: approve_expression(service, workspace, body),
        "final-review": lambda: final_review(service, workspace, body),
        "analyze": lambda: service.analyze(workspace, manual),
        "evidence-map": lambda: service.map_evidence(workspace, manual,
            local_vector=body.get("semantic_query_vector"), local_profile_id=body.get("semantic_profile_id")),
        "strategy": lambda: service.strategy(workspace, manual),
        "question-portfolio": lambda: plan_portfolio(service, workspace, manual),
        "approve-portfolio": lambda: approve_portfolio(service, workspace),
        "approve-strategy": lambda: service.approve_strategy(workspace),
        "add-question": lambda: service.add_question(workspace, body["text"], int(body.get("limit", 1000))),
        "question-brief": lambda: service.question_brief(workspace, qid, manual),
        "claim-test": lambda: service.test_claim(workspace, qid, manual, body.get("confirmed") is True),
        "approve-question": lambda: service.approve_question(workspace, qid),
        "generate": lambda: service.draft(workspace, qid, manual),
        "review": lambda: service.review(
            workspace, qid, body.get("manual_verified") is True, body.get("resume", False)
        ),
        "review-answers": lambda: service.answer_review(
            workspace, qid, body["responses"], body.get("resume") is True, body.get("manual_verified") is True
        ),
        "patch": lambda: service.patch_document(
            workspace,
            qid,
            body.get("old_text", ""),
            body.get("new_text", ""),
            body.get("protected"),
            resume=body.get("resume", False),
        ),
        "ledger": lambda: service.update_ledger(workspace, qid, body["claims"], body.get("resume", False)),
        "revise": lambda: service.revise(workspace, qid, body.get("resume", False)),
        "final-lock": lambda: service.final_lock(workspace, qid, body.get("resume", False)),
        "resume": lambda: service.resume(workspace, manual, body.get("page_budget", 1)),
        "ready": lambda: service.ready(workspace),
        "freeze": lambda: service.freeze(workspace),
        "confirm": lambda: service.confirm_submission(workspace, body.get("confirmed") is True),
        "close": lambda: service.close_application(
            workspace, body.get("confirmed") is True, body.get("reason", "")
        ),
        "interview-handoff": lambda: service.handoff(workspace),
        "outcome": lambda: service.outcome(workspace, body["result"], body.get("notes", "")),
        "postmortem": lambda: service.postmortem(workspace, body.get("draft_hypotheses") is True),
        "commands": lambda: service.command(workspace, body["text"], qid, body.get("evidence_id", "")),
    }
    if action not in operations:
        raise HTTPException(404, "지원하지 않는 작업입니다.")
    from career.activity import run_operation

    def execute():
        service.ws(workspace)
        if action == "claim-test" and manual is not None and not body.get("artifact_id"):
            raise ValueError("원문과 대조한 문항 메시지 버전을 지정해 주세요.")
        if approval_kind and body.get("artifact_id"):
            current = service.artifact(
                workspace,
                approval_kind,
                qid
                if approval_kind not in {"ApplicationBrief", "ResumeContent", "QuestionPortfolio"}
                else "",
            )
            if current.id != body["artifact_id"]:
                raise ValueError("검토 중 문서 버전이 바뀌었습니다. 현재 내용을 다시 확인해 주세요.")
        return operations[action]()

    manual_supported = {"assess-opportunity", "research", "research-extract", "analyze", "evidence-map", "strategy",
                        "question-portfolio", "question-brief", "claim-test", "generate", "resume"}
    manual_action = (action in manual_supported and bool(manual)) or (action == "review" and body.get("manual_verified") is True)
    manual_action = manual_action or (action == "research" and body.get("live") is not True)
    manual_action = manual_action or (action == "research-extract" and manual is not None)
    manual_action = manual_action or (action == "review-answers" and body.get("manual_verified") is True)
    manual_action = manual_action or (action == "postmortem" and body.get("draft_hypotheses") is not True)
    result = run_operation(db, ident, workspace, action, execute, uses_ai=False if manual_action else None)
    result = view(result) if hasattr(result, "__table__") else result
    if idempotency_key:
        result = json.loads(json.dumps(result, default=str))
        db.add(
            Record(
                user_id=ident,
                kind="Idempotency",
                data={"key": idempotency_key, "workspace": workspace, "digest": digest, "result": result},
            )
        )
    return result


@app.get("/api/applications/{workspace}/submission")
def submission(workspace: str, db: DB, ident: User):
    ws = owned(db, Workspace, ident, workspace)
    bundle = Workflow(db, ident).artifact(workspace, "SubmissionBundle")
    return {"bundle": view(bundle), "submitted_at": ws.data.get("submitted_at")}


@app.get("/api/applications/{workspace}/resume/export", response_class=PlainTextResponse)
def resume_export(workspace: str, db: DB, ident: User):
    owned(db, Workspace, ident, workspace)
    item = Workflow(db, ident).artifact(workspace, "ResumeContent")
    return item.data["text"]


@app.delete("/api/applications/{workspace}")
def delete_workspace(workspace: str, db: DB, ident: User):
    ws = owned(db, Workspace, ident, workspace)
    if db.scalar(
        select(ExecutionRun).where(
            ExecutionRun.user_id == ident,
            ExecutionRun.workspace_id == workspace,
            ExecutionRun.active_key == "RUNNING",
        )
    ):
        raise ValueError("진행 중인 작업이 완료된 뒤 삭제해 주세요.")
    outcome_ids = {
        r.id
        for r in db.scalars(select(Record).where(Record.user_id == ident, Record.kind == "SelectionOutcome"))
        if r.data.get("workspace_id") == workspace
    }
    for source in db.scalars(select(Source).where(Source.user_id == ident)):
        if source.path in {"outcomes/" + i for i in outcome_ids}:
            invalidate_source(db, ident, source.id, delete_content=True)
    for model in APPLICATION_MODELS:
        for row in db.scalars(select(model).where(model.user_id == ident, model.workspace_id == workspace)):
            db.delete(row)
    db.flush()
    for model, field in [
        (EditorDraft, EditorDraft.workspace_id),
        (ExecutionRun, ExecutionRun.workspace_id),
        (Artifact, Artifact.workspace_id),
        (Feedback, Feedback.application_id),
        (Revision, Revision.application_id),
    ]:
        for item in db.scalars(select(model).where(model.user_id == ident, field == workspace)):
            db.delete(item)
    for record in db.scalars(select(Record).where(Record.user_id == ident)):
        if record.data.get("workspace_id", record.data.get("workspace")) == workspace:
            db.delete(record)
    for trace in db.scalars(select(PromptRun).where(PromptRun.user_id == ident)):
        if trace.data.get("workspace_id") == workspace:
            db.delete(trace)
    db.delete(ws)
    return {"deleted": True}


@app.get("/api/telemetry")
def telemetry(db: DB, ident: User):
    from career.evaluation import production_metrics, reviewer_metrics

    events = export_events(db, ident)
    traces = [view(t) for t in db.scalars(select(PromptRun).where(PromptRun.user_id == ident))]
    accepted = sum(e["action"] == "ACCEPT" for e in events)
    return {
        "events": events,
        "traces": traces,
        "decision_acceptance": accepted / len(events) if events else None,
        "ablation_status": "PRODUCTION_DATA_REQUIRED",
        "product_metrics": production_metrics(db, ident),
        "reviewer_metrics": reviewer_metrics(
            [
                r.data
                for r in db.scalars(
                    select(Record).where(Record.user_id == ident, Record.kind == "ReviewIssueLabel")
                )
            ]
        ),
    }


class ReviewLabel(BaseModel):
    issue_index: int = Field(ge=0)
    valid: bool
    accepted: bool | None = None


@app.post("/api/artifacts/{artifact_id}/review-labels")
def label_review(artifact_id: str, body: ReviewLabel, db: DB, ident: User):
    artifact = owned(db, Artifact, ident, artifact_id)
    if artifact.kind not in {"Review", "ResumeReview", "PortfolioReview"} or body.issue_index >= len(
        artifact.data.get("issues", [])
    ):
        raise ValueError("평가할 검수 의견을 선택해 주세요.")
    existing = next(
        (
            r
            for r in db.scalars(
                select(Record).where(Record.user_id == ident, Record.kind == "ReviewIssueLabel")
            )
            if r.data.get("artifact_id") == artifact_id and r.data.get("issue_index") == body.issue_index
        ),
        None,
    )
    data = {
        **body.model_dump(),
        "workspace_id": artifact.workspace_id,
        "artifact_id": artifact_id,
        "artifact_version": artifact.version,
        "issue": artifact.data["issues"][body.issue_index],
    }
    record = existing or Record(user_id=ident, kind="ReviewIssueLabel", data=data)
    record.data = data
    db.add(record)
    db.flush()
    return view(record)


@app.get("/api/export")
def personal_export(db: DB, ident: MemberUser):
    return {
        model.__tablename__: [view(row) for row in db.scalars(select(model).where(model.user_id == ident))]
        for model in (
            Source,
            Fact,
            Evidence,
            Workspace,
            Artifact,
            Record,
            Feedback,
            Revision,
            PromptRun,
            ExecutionRun,
            EditorDraft,
            LocalEvidenceEmbedding,
            AIUsageSettings,
            AIUsageBucket,
            AIUsageReservation,
            ServiceMember,
            RequestRateBucket,
            *ENTITY_MODELS.values(),
            *APPLICATION_MODELS,
            CorrectionRecord,
        )
    }


from career.account_routes import build_account_router  # noqa: E402
from career.expanded_routes import build_expanded_router  # noqa: E402
from career.public_routes import make_router as build_public_router  # noqa: E402
from career.rest_routes import router  # noqa: E402
from career.upgrade_routes import build_router  # noqa: E402

app.include_router(router)
app.include_router(build_router(database, user))
app.include_router(build_public_router(database, identity_member))
app.include_router(build_account_router(database, identity_only))
app.include_router(build_expanded_router(database, user))


@app.post("/api/evals/run")
def run_evaluation(body: dict[str, Any], db: DB, ident: User):
    from career.service_access import shared_service

    if shared_service() and body.get("mode") in {"workflow_ablation", "historical", "ablation"}:
        raise HTTPException(403, "공용 서비스에서는 외부 모델 비교 실험을 실행하지 않습니다.")
    from career.evaluation import benchmark, historical_smoke, production_metrics
    from career.providers import OpenAIProvider

    if body.get("mode") == "workflow_ablation":
        if body.get("confirmed_external_eval") is not True:
            raise ValueError("이 지원 작업과 검색된 개인 자료를 외부 모델로 평가하는 작업을 확인해 주세요.")
        from career.workflow_evaluation import workflow_ablation

        data = workflow_ablation(
            Workflow(db, ident),
            body["workspace_id"],
            body["question_id"],
            tuple(body.get("systems", ["B0", "B1", "B2", "B3"])),
            body.get("accepted_text"),
        )
    elif body.get("mode") == "historical":
        if body.get("confirmed_external_eval") is not True:
            raise ValueError("과거 사례의 외부 모델 전송 확인이 필요합니다.")
        cases = [
            json.loads(line) for line in Path("evals/historical_cases.jsonl").read_text("utf-8").splitlines()
        ]
        data = historical_smoke(OpenAIProvider(), cases)
    elif body.get("mode") == "ablation":
        if body.get("confirmed_external_eval") is not True:
            raise ValueError("평가 자료의 외부 모델 전송 확인이 필요합니다.")
        data = benchmark(OpenAIProvider(), body["case"])
    else:
        data = production_metrics(db, ident)
    record = Record(user_id=ident, kind="EvalRun", data=data)
    db.add(record)
    db.flush()
    return view(record)


@app.get("/api/evals/runs/{run_id}")
def evaluation_result(run_id: str, db: DB, ident: User):
    record = owned(db, Record, ident, run_id)
    if record.kind != "EvalRun":
        raise LookupError("평가 기록이 아닙니다.")
    return view(record)


@app.get("/api/traces/{run_id}")
def trace_result(run_id: str, db: DB, ident: User):
    return view(owned(db, PromptRun, ident, run_id))
