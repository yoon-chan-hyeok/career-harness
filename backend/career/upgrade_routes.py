"""Authenticated adapters for provenance, recovery, usage and local documents."""

import base64
from typing import Callable, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from career.artifacts import latest
from career.document_exports import render_docx, render_pdf
from career.document_uploads import UploadDecision, UploadRequest, confirm_upload, upload_preview
from career.editor_drafts import DraftRequest, delete_draft, read_draft, save_draft
from career.models import Artifact, PromptRun, Source, Workspace
from career.provenance import artifact_provenance
from career.provider_config import provider_settings
from career.semantic import IndexRequest, SearchRequest, documents, index, profile_info, semantic_search
from career.truth import owned
from career.usage_limits import configure_usage, usage_status


def build_router(database_dep: Callable, user_dep: Callable):
    router = APIRouter(prefix="/api")

    @router.get("/artifacts/{artifact_id}/provenance")
    def provenance(artifact_id: str, db: Session = Depends(database_dep), ident: str = Depends(user_dep)):
        return artifact_provenance(db, ident, artifact_id)

    @router.get("/editor-drafts/{key:path}")
    def draft_read(key: str, db: Session = Depends(database_dep), ident: str = Depends(user_dep)):
        return read_draft(db, ident, key)

    @router.put("/editor-drafts/{key:path}")
    def draft_write(key: str, body: DraftRequest, db: Session = Depends(database_dep), ident: str = Depends(user_dep)):
        return save_draft(db, ident, key, body)

    @router.delete("/editor-drafts/{key:path}")
    def draft_delete(key: str, db: Session = Depends(database_dep), ident: str = Depends(user_dep)):
        return delete_draft(db, ident, key)

    @router.get("/usage")
    def usage(db: Session = Depends(database_dep), ident: str = Depends(user_dep)):
        return usage_status(db, ident)

    @router.get("/providers/activity")
    def provider_activity(db: Session = Depends(database_dep), ident: str = Depends(user_dep)):
        snapshot = provider_settings()
        success = db.scalar(select(PromptRun).where(PromptRun.user_id == ident,
                            PromptRun.data["status"].as_string() == "COMPLETED",
                            PromptRun.data["workspace_id"].as_string().is_not(None),
                            PromptRun.stage != "provider_connection_check",
                            func.lower(PromptRun.provider).in_(["huggingface", "groq", "openai"]))
                            .order_by(PromptRun.created_at.desc()).limit(1))
        return {"last_success": {"provider": success.provider.casefold(), "model": success.data.get("model"),
                                 "at": success.created_at, "stage": success.stage,
                                 "latency_ms": success.data.get("latency_ms"),
                                 "current_configuration_matches": success.provider.casefold() == snapshot.provider
                                 and success.data.get("model") == snapshot.model} if success else None,
                "notice": "지원 작업의 실제 AI 응답 기록입니다. 연결 확인용 인사 요청과 현재 계정의 원격 잔액은 포함하지 않습니다."}

    @router.get("/usage/limits")
    def usage_limits(db: Session = Depends(database_dep), ident: str = Depends(user_dep)):
        value = usage_status(db, ident)
        return {key: value[key] for key in ("limits", "defaults", "notice")}

    @router.put("/usage/limits")
    def limits_write(body: dict, db: Session = Depends(database_dep), ident: str = Depends(user_dep)):
        return configure_usage(db, ident, body)

    @router.get("/semantic/profile")
    def semantic_profile(ident: str = Depends(user_dep)):
        return profile_info()

    @router.get("/semantic/documents")
    def semantic_documents(kind: Literal["FACT", "EXPRESSION"] = "FACT", cursor: str | None = Query(None, max_length=64),
                           db: Session = Depends(database_dep), ident: str = Depends(user_dep)):
        return documents(db, ident, kind, cursor)

    @router.post("/semantic/index")
    def semantic_index(body: IndexRequest, db: Session = Depends(database_dep), ident: str = Depends(user_dep)):
        return index(db, ident, body)

    @router.post("/semantic/search")
    def semantic_find(body: SearchRequest, db: Session = Depends(database_dep), ident: str = Depends(user_dep)):
        return semantic_search(db, ident, body)

    @router.post("/sources/upload")
    def upload(body: UploadRequest, db: Session = Depends(database_dep), ident: str = Depends(user_dep)):
        return upload_preview(db, ident, body)

    @router.post("/sources/uploads/{source_id}/confirm")
    def upload_confirm(source_id: str, body: UploadDecision, db: Session = Depends(database_dep), ident: str = Depends(user_dep)):
        return confirm_upload(db, ident, source_id, body)

    @router.get("/sources/uploads/{source_id}/original")
    def original(source_id: str, db: Session = Depends(database_dep), ident: str = Depends(user_dep)):
        source = owned(db, Source, ident, source_id)
        upload = source.data.get("upload", {})
        if source.status in {"DO_NOT_USE", "SUPERSEDED"} or not upload.get("original_base64"):
            raise LookupError("원본 파일을 찾을 수 없습니다.")
        return Response(base64.b64decode(upload["original_base64"]), media_type="application/octet-stream",
                        headers={"Cache-Control": "private, no-store",
                                 "Content-Disposition": "attachment; filename*=UTF-8''" + quote(upload["filename"])})

    @router.get("/applications/{workspace}/resume/download")
    def download(workspace: str, format: Literal["pdf", "docx"] = "pdf", artifact_id: str | None = None,
                 db: Session = Depends(database_dep), ident: str = Depends(user_dep)):
        owned(db, Workspace, ident, workspace)
        item = (owned(db, Artifact, ident, artifact_id) if artifact_id
                else latest(db, ident, workspace, "ResumeContent"))
        if item is None or item.kind != "ResumeContent" or item.workspace_id != workspace:
            raise LookupError("이력서 버전을 선택해 주세요.")
        result = render_pdf(item.data) if format == "pdf" else render_docx(item.data)
        filename = f"이력서-v{item.version}.{format}"
        headers = {"Cache-Control": "private, no-store", "X-Artifact-Id": item.id,
                   "Content-Disposition": "inline; filename*=UTF-8''" + quote(filename),
                   "X-Page-Budget": str(result.page_budget), "X-Page-Overflow": str(result.overflow).lower()}
        if result.pages is not None:
            headers["X-Page-Count"] = str(result.pages)
        return Response(result.content, media_type=result.media_type, headers=headers)

    return router
