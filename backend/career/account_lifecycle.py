"""Own-account deletion: durable closure, Career purge, then Supabase Auth deletion.

Lifecycle transactions are independent of the request business transaction and
take the same global lock as admission, quota reservation and the write fence.
No provider reservation is refunded and no external HTTP runs under a DB lock.
"""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import httpx
from fastapi import HTTPException
from sqlalchemy import delete, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from career.access_config import account_admin_key
from career.admin import is_admin
from career.authentication import authentication_configuration, require_recent_otp
from career.db import Base, Record, now
from career.models import ServiceMember
from career.service_access import SHARED_BUDGET_USER
from career.usage_limits import DEFAULT_LIMITS, _settings

RECEIPT_KIND = "AccountDeletionReceipt"
RETAINED_TABLES = frozenset({
    "service_members", "ai_usage_settings", "ai_usage_buckets", "ai_usage_reservations",
})
RETAINED_DATA = ["account_access_tombstone", "usage_accounting", "deletion_receipt"]
OTP_MAX_AGE_SECONDS = 300


@dataclass(frozen=True)
class AdminConfiguration:
    origin: str
    key: str = field(repr=False)
    legacy: bool = False


class DeletionPending(Exception):
    """Only a fixed, redacted response survives a failed lifecycle operation."""

    def __init__(self, career_data_deleted: bool):
        self.payload = {
            "status": "DELETION_PENDING", "access_closed": True,
            "career_data_deleted": career_data_deleted, "auth_account_deleted": False,
            "retry_allowed": True,
            "detail": "계정 접근은 차단됐습니다. 삭제가 완료되지 않아 이메일 인증 후 다시 시도해 주세요.",
        }
        super().__init__(self.payload["detail"])


def admin_configuration() -> AdminConfiguration:
    """Read only server-owned credentials; user input never selects a destination."""
    try:
        config = authentication_configuration()
        if config.mode != "supabase":
            raise ValueError()
        key, legacy = account_admin_key()
        return AdminConfiguration(config.issuer.removesuffix("/auth/v1"), key, legacy)
    except ValueError:
        raise HTTPException(503, "계정 삭제 연결 설정이 필요합니다. 운영자에게 문의해 주세요.") from None


def _receipt(db: Session, user: str) -> Record | None:
    return db.scalar(select(Record).where(Record.user_id == user, Record.kind == RECEIPT_KIND)
                     .execution_options(populate_existing=True))


def _deletion_state(receipt: Record | None) -> dict[str, Any]:
    data = receipt.data if receipt else {}
    status = data.get("status", "NONE")
    return {
        "status": status if status in {"NONE", "REQUESTED", "CAREER_DATA_DELETED", "DELETED"} else "REQUESTED",
        "career_data_deleted": data.get("career_data_deleted") is True,
        "auth_account_deleted": data.get("auth_account_deleted") is True,
    }


def account_status(db: Session, user: str) -> dict[str, Any]:
    from career.guest_access import enabled

    guest = enabled()
    member = db.get(ServiceMember, user, populate_existing=True)
    receipt = _receipt(db, user)
    closed = bool(receipt or member is not None and member.status != "ACTIVE")
    unavailable = None
    if is_admin(user):
        unavailable = "OPERATOR_ACCOUNT"
    else:
        try:
            if guest:
                pass
            elif authentication_configuration().mode != "supabase":
                unavailable = "SUPABASE_REQUIRED"
            else:
                admin_configuration()
        except (ValueError, HTTPException):
            unavailable = "SERVER_DELETE_UNAVAILABLE"
    state = _deletion_state(receipt)
    return {
        "status": "CLOSED" if closed else "ACTIVE",
        "can_export": not closed, "export_url": "/api/export",
        "can_delete": unavailable is None and state["status"] != "DELETED",
        "delete_unavailable_reason": unavailable,
        "deletion": state, "requires_recent_email_otp": not guest,
        "reauthentication_max_age_seconds": OTP_MAX_AGE_SECONDS,
        "retained_data": RETAINED_DATA,
        "notice": ("삭제 시 현재 체험 자료와 연결 정보를 제거합니다. 접근 차단 기록·사용량 장부·삭제 처리 기록은 보존합니다."
                   if guest else "삭제 시 취업 자료와 로그인 계정을 제거합니다. 접근 차단 기록·사용량 장부·삭제 처리 기록은 보존합니다. 기존 운영 백업의 보관 정책은 개인정보 안내를 확인해 주세요."),
    }


def _ensure_independent(db: Session):
    if db.in_transaction() or db.new or db.dirty or db.deleted:
        # Opening another connection while a pool-of-one business session owns
        # one would hang. Never silently commit unrelated business writes.
        raise HTTPException(409, "진행 중인 저장을 마친 뒤 계정 삭제를 다시 시도해 주세요.")


def _lifecycle_session(db: Session) -> Session:
    session = Session(db.get_bind(), expire_on_commit=False)
    session.info["career_lifecycle_transaction"] = True
    return session


def _close_access(db: Session, user: str):
    with _lifecycle_session(db) as lifecycle, lifecycle.begin():
        _settings(lifecycle, SHARED_BUDGET_USER, lock=True)
        member = lifecycle.get(ServiceMember, user, populate_existing=True)
        if member is None:
            member = ServiceMember(user_id=user)
            lifecycle.add(member)
        member.status = "SUSPENDED"
        member.limits = {key: None if value is None else 0 for key, value in DEFAULT_LIMITS.items()}
        member.updated_at = now()
        if _receipt(lifecycle, user) is None:
            lifecycle.add(Record(user_id=user, kind=RECEIPT_KIND, data={
                "status": "REQUESTED", "requested_at": now().isoformat(),
                "career_data_deleted": False, "auth_account_deleted": False,
            }))


def _purge_career_data(db: Session, user: str):
    # Import the registry so standalone lifecycle callers include every model,
    # including editor drafts, local vectors and future user-owned tables.
    from career import models  # noqa: F401

    with _lifecycle_session(db) as lifecycle, lifecycle.begin():
        _settings(lifecycle, SHARED_BUDGET_USER, lock=True)
        member = lifecycle.get(ServiceMember, user, populate_existing=True)
        receipt = _receipt(lifecycle, user)
        if member is None or member.status != "SUSPENDED" or receipt is None:
            raise RuntimeError("Account closure must be committed before purge")
        if lifecycle.get_bind().dialect.name == "postgresql":
            lifecycle.execute(text("DELETE FROM evidence_embeddings WHERE user_id = :user"), {"user": user})
        for table in reversed(Base.metadata.sorted_tables):
            if table.name in RETAINED_TABLES or "user_id" not in table.c:
                continue
            statement = delete(table).where(table.c.user_id == user)
            if table.name == Record.__tablename__:
                statement = statement.where(table.c.kind != RECEIPT_KIND)
            lifecycle.execute(statement)
        users = Base.metadata.tables.get("users")
        if users is not None:
            lifecycle.execute(delete(users).where(users.c.id == user))
        receipt.data = {
            **receipt.data, "status": "CAREER_DATA_DELETED",
            "career_data_deleted": True, "career_deleted_at": now().isoformat(),
        }


def _delete_auth_account(config: AdminConfiguration, user: str, transport: httpx.BaseTransport | None):
    headers = {"apikey": config.key}
    if config.legacy:
        headers["Authorization"] = "Bearer " + config.key
    # New secret keys are opaque API keys, not bearer JWTs. The project gateway
    # resolves the privileged apikey; legacy service-role JWTs use both headers.
    with httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0), follow_redirects=False,
                      trust_env=False, transport=transport) as client:
        response = client.request("DELETE", config.origin + "/auth/v1/admin/users/" + user,
                                  headers=headers, json={"should_soft_delete": False})
        if response.status_code == 404:
            # Retry after a crash may find that the previous deletion succeeded.
            # A generic route/proxy 404 must never be reported as completion.
            try:
                missing = response.json().get("code") == "user_not_found"
            except (ValueError, AttributeError):
                missing = False
            if missing:
                return
        response.raise_for_status()


def _mark_complete(db: Session, user: str):
    with _lifecycle_session(db) as lifecycle, lifecycle.begin():
        _settings(lifecycle, SHARED_BUDGET_USER, lock=True)
        receipt = _receipt(lifecycle, user)
        if receipt is None or receipt.data.get("career_data_deleted") is not True:
            raise RuntimeError("Missing deletion receipt")
        receipt.data = {
            **receipt.data, "status": "DELETED", "auth_account_deleted": True,
            "auth_deleted_at": now().isoformat(),
        }


def delete_account(db: Session, user: str, confirmation: str, reauthentication_token: str,
                   *, transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    if confirmation != "DELETE":
        raise HTTPException(409, "삭제 확인란에 DELETE를 입력해 주세요.")
    if is_admin(user):
        raise HTTPException(403, "운영자 계정은 이 화면에서 삭제할 수 없습니다.")
    try:
        subject = str(UUID(user))
    except ValueError:
        raise HTTPException(401, "유효한 로그인 계정이 필요합니다.") from None
    if subject != user:
        raise HTTPException(401, "유효한 로그인 계정이 필요합니다.")
    from career.guest_access import delete_guest, enabled, verify_session

    if enabled():
        verify_session(db, user, "Bearer " + reauthentication_token)
        db.rollback()
        return delete_guest(db, user)
    require_recent_otp("Bearer " + reauthentication_token, user, OTP_MAX_AGE_SECONDS)
    config = admin_configuration()
    _ensure_independent(db)
    # Precondition failures above never suspend an account. From this commit on,
    # ordinary API requests and quota reservations must reject the tombstone.
    try:
        _close_access(db, user)
    except SQLAlchemyError:
        raise HTTPException(503, "계정 접근 차단을 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.") from None
    try:
        _purge_career_data(db, user)
    except (SQLAlchemyError, RuntimeError):
        raise DeletionPending(False) from None
    try:
        _delete_auth_account(config, user, transport)
    except (httpx.HTTPError, ValueError):
        raise DeletionPending(True) from None
    try:
        _mark_complete(db, user)
    except (SQLAlchemyError, RuntimeError):
        # Data and Auth deletion both completed; a receipt write failure cannot
        # undo either operation or incorrectly claim that private data remains.
        pass
    return {
        "status": "DELETED", "access_closed": True, "career_data_deleted": True,
        "auth_account_deleted": True, "retry_allowed": False,
    }
