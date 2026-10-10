"""Operator-managed membership, with optional verified public admission."""

import os
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select

from career.access_config import access_mode as access_mode
from career.authentication import is_production
from career.db import Record, now
from career.models import ServiceMember

SHARED_BUDGET_USER = "__career_shared_budget__"


def shared_service() -> bool:
    return access_mode() == "public" or is_production() or os.getenv("CAREER_SHARED_SERVICE", "0") == "1"


def bootstrap_members() -> set[str]:
    return {s.strip() for name in ("CAREER_ALLOWED_USER_IDS", "CAREER_ADMIN_USER_IDS")
            for s in os.getenv(name, "").split(",") if s.strip()}


def require_member(db, user: str):
    if user.startswith("__career_"):
        raise HTTPException(403, "예약된 계정은 로그인할 수 없습니다.")
    if not shared_service():
        return
    member = db.get(ServiceMember, user, populate_existing=True)
    if member is not None:
        if member.status == "ACTIVE":
            return
    elif access_mode() != "public" and user in bootstrap_members():
        return
    message = ("서비스 이용이 중지되었거나 계정 확인이 필요합니다. 운영자에게 문의해 주세요."
               if access_mode() == "public" else "초대가 승인된 계정만 사용할 수 있습니다. 운영자에게 접근 권한을 확인해 주세요.")
    raise HTTPException(403, message)


def ceiling(db, user: str):
    from career.usage_limits import DEFAULT_LIMITS, validate_limits

    member = db.get(ServiceMember, user)
    return validate_limits(member.limits if member else DEFAULT_LIMITS)


def effective_limits(db, user: str, personal: dict):
    if not shared_service() or user == SHARED_BUDGET_USER:
        return personal
    return intersect_limits(personal, ceiling(db, user))


def intersect_limits(personal: dict, managed: dict):
    return {key: min(value, managed[key]) if value is not None and managed[key] is not None
            else managed[key] if value is None else value for key, value in personal.items()}


def require_operator(user: str):
    from career.admin import is_admin

    if not is_admin(user):
        raise HTTPException(403, "운영자만 계정과 공용 한도를 변경할 수 있습니다.")


def configure_member(db, operator: str, subject: str, status: str, limits: dict):
    from career.usage_limits import _settings, validate_limits

    require_operator(operator)
    if (not subject or len(subject) > 64 or subject.startswith("__career_")
            or status not in {"ACTIVE", "SUSPENDED"}):
        raise ValueError("초대 계정과 사용 상태를 확인해 주세요.")
    if is_production():
        try:
            subject = str(UUID(subject))
        except ValueError:
            raise ValueError("Supabase 사용자의 UUID를 입력해 주세요.") from None
    if subject == operator and status != "ACTIVE":
        raise ValueError("현재 운영자 계정은 이 화면에서 중지할 수 없습니다.")
    checked = validate_limits(limits)
    # Same global lock order as reservation/settlement, so a quota edit cannot race a new reservation.
    _settings(db, SHARED_BUDGET_USER, lock=True)
    if status == "ACTIVE" and db.scalar(select(Record.id).where(
        Record.user_id == subject, Record.kind == "AccountDeletionReceipt"
    ).limit(1)):
        raise ValueError("삭제 절차를 시작한 계정은 다시 활성화할 수 없습니다.")
    member = db.get(ServiceMember, subject)
    if member is None:
        member = ServiceMember(user_id=subject)
        db.add(member)
    member.status, member.limits, member.updated_at = status, checked, now()
    db.add(Record(user_id=operator, kind="ServiceAccessChanged",
                  data={"subject": subject, "status": status, "limits": checked}))
    db.flush()
    return {"user_id": subject, "status": status, "limits": checked}


def service_status(db, operator: str, after: str = "", prefix: str = "", limit: int = 50):
    from career.usage_limits import usage_status, validate_limits

    require_operator(operator)
    limit = min(100, max(1, limit))
    next_cursor = None
    if access_mode() == "public":
        match = ServiceMember.user_id.startswith(prefix, autoescape=True)
        query = select(ServiceMember).where(match, ServiceMember.user_id > after).order_by(ServiceMember.user_id)
        rows = list(db.scalars(query.limit(limit + 1)))
        if len(rows) > limit:
            next_cursor = rows[limit - 1].user_id
        members = [{"user_id": row.user_id, "status": row.status, "limits": validate_limits(row.limits)}
                   for row in rows[:limit]]
        total = db.scalar(select(func.count()).select_from(ServiceMember).where(match)) or 0
    else:
        saved = {member.user_id: member for member in db.scalars(select(ServiceMember))}
        users = sorted(user for user in set(saved) | bootstrap_members() if user.startswith(prefix))
        total = len(users)
        users = [user for user in users if user > after]
        if len(users) > limit:
            next_cursor = users[limit - 1]
        members = [{"user_id": user, "status": saved[user].status if user in saved else "ACTIVE",
                    "limits": ceiling(db, user)} for user in users[:limit]]
    return {"enabled": shared_service(), "access_mode": access_mode(), "members": members,
            "total_members": total, "next_cursor": next_cursor,
            "shared_usage": usage_status(db, SHARED_BUDGET_USER),
            "notice": "계정별 한도와 공용 한도를 함께 적용합니다. 계정을 중지하면 기존 로그인도 차단되며 개인 문서는 표시하지 않습니다."}
