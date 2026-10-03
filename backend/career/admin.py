"""Personal administration: explicit authorization and current-account summaries."""

import os
import re
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError

from career.activity import ACTION_LABELS, serialize_run
from career.authentication import is_production
from career.models import Artifact, Evidence, ExecutionRun, Source, Workspace
from career.provider_config import provider_status, require_local_owner
from career.usage_limits import usage_status

SAFE_ERROR_CODES = frozenset({"PROVIDER_UNAVAILABLE", "NEEDS_USER_ACTION", "EXECUTION_FAILED",
                              "EXECUTION_INTERRUPTED", "BUDGET_EXCEEDED", "REQUEST_DEADLINE_EXCEEDED"})


def is_admin(user: str) -> bool:
    configured = [part.strip() for part in os.getenv("CAREER_ADMIN_USER_IDS", "").split(",") if part.strip()]
    if is_production():
        # The ordinary user allowlist grants service access, never admin access.
        try:
            administrators = {str(UUID(part)) for part in configured}
        except ValueError:
            return False
        return user in administrators
    if configured and all(len(part) <= 64 for part in configured) and user in configured:
        return True
    try:
        require_local_owner(user)
        return True
    except HTTPException:
        return False


def source_repository_url() -> str | None:
    value = os.getenv("CAREER_SOURCE_REPOSITORY_URL", "").strip()
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if (parsed.scheme != "https" or parsed.netloc != "github.com" or parsed.query or parsed.fragment
            or not re.fullmatch(r"/[A-Za-z0-9_-]{1,100}/[A-Za-z0-9_.-]{1,100}/?", parsed.path)):
        return None
    return "https://github.com" + parsed.path.rstrip("/")


def status(db, user):
    if not is_admin(user):
        raise HTTPException(403, "관리자 권한이 있는 계정만 이 페이지를 사용할 수 있습니다.")
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise HTTPException(503, "데이터베이스 상태를 확인할 수 없습니다.") from None

    def count(model, *conditions):
        return db.scalar(select(func.count()).select_from(model).where(model.user_id == user, *conditions)) or 0

    counts = {"applications": count(Workspace), "sources": count(Source), "evidence": count(Evidence),
              "artifacts": count(Artifact), "pending_approvals": count(
                  Artifact, Artifact.status == "ACTIVE",
                  Artifact.kind.in_(["ApplicationBrief", "QuestionBrief", "QuestionPortfolio"])),
              "stale_artifacts": count(Artifact, Artifact.status == "STALE"),
              "failed_executions": count(ExecutionRun, ExecutionRun.status == "FAILED")}
    recent = list(db.scalars(select(ExecutionRun).where(ExecutionRun.user_id == user)
                            .order_by(ExecutionRun.created_at.desc()).limit(15)))
    runs = [{"id": run.id, "workspace_id": run.workspace_id,
             "action": run.action if run.action in ACTION_LABELS else "other",
             "label": ACTION_LABELS.get(run.action, "작업 처리"),
             "status": run.status, "started_at": serialize_run(run)["started_at"],
             "finished_at": serialize_run(run)["finished_at"],
             "elapsed_ms": run.elapsed_ms,
             "error_code": run.error_code if run.error_code in SAFE_ERROR_CODES else None} for run in recent]
    try:
        provider = provider_status(user)
    except ValueError:
        provider = {"provider": "none", "model": "", "configured": False, "live_verified": False,
                    "verified_at": None, "editable": False, "credential_source": "missing",
                    "free_only_confirmed": False, "token_configured": False}
    auth_mode = os.getenv("AUTH_MODE", "local").strip().lower()
    repository = source_repository_url()
    dialect = db.get_bind().dialect.name
    connections = [
        {"key": "ai", "label": "AI 제공자", "status": "verified" if provider["live_verified"]
         else "configured" if provider["configured"] else "missing",
         "detail": "연결 확인 기록과 설정 상태입니다. 실제 문서 응답은 지원 작업의 실행 기록에서 확인하세요."},
        {"key": "authentication", "label": "로그인", "status": "configured",
         "detail": "Supabase 서버 검증을 사용합니다." if auth_mode == "supabase" else "개인 로컬 인증을 사용합니다."},
        {"key": "database", "label": "데이터베이스", "status": "available",
         "detail": "현재 서버의 데이터베이스 응답을 확인했습니다."},
        {"key": "deployment", "label": "운영 배포", "status": "unverified",
         "detail": "운영 HTTPS·클라우드 배포 상태는 이 페이지에서 외부 조회하지 않습니다."},
        {"key": "source_repository", "label": "GitHub 소스", "status": "configured" if repository else "missing",
         "detail": "설정한 소스 저장소 링크입니다. 최신 소스 업로드·CI 성공 여부는 별도 확인이 필요합니다."},
    ]
    return {"is_admin": True, "scope": "CURRENT_ACCOUNT", "environment": os.getenv("CAREER_ENV", "development"),
            "authentication_mode": auth_mode, "database": {"status": "ok", "dialect": dialect},
            "counts": counts, "recent_executions": runs, "usage": usage_status(db, user),
            "provider": provider, "connections": connections, "source_repository_url": repository,
            "notice": "현재 로그인 계정의 요약만 표시합니다. 다른 사용자의 자료·비밀키·문서 원문은 포함하지 않습니다."}
