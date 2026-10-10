"""Bound retained upload payloads for a small shared service, across workers."""

import os

from sqlalchemy import Text, cast, func, select

from career.models import Source
from career.service_access import SHARED_BUDGET_USER, shared_service


def check_upload_capacity(db, user: str, path: str, incoming_bytes: int):
    if not shared_service():
        return
    from career.usage_limits import _settings

    _settings(db, SHARED_BUDGET_USER, lock=True)
    if db.scalar(select(Source.id).where(Source.user_id == user, Source.path == path)):
        return  # A repeated identical upload is handled idempotently by register_source.
    for subject, prefix, byte_default, count_default in (
        (user, "CAREER_USER_UPLOAD", 20_000_000, 50),
        (None, "CAREER_SHARED_UPLOAD", 100_000_000, 250),
    ):
        try:
            byte_limit = int(os.getenv(prefix + "_BYTES", str(byte_default)))
            count_limit = int(os.getenv(prefix + "_COUNT", str(count_default)))
            if not 0 <= byte_limit <= 1_000_000_000 or not 0 <= count_limit <= 10000:
                raise ValueError()
        except ValueError:
            raise ValueError("자료 보관 한도 설정을 확인해 주세요.") from None
        # PostgreSQL/SQLite JSON serialization differs. Four bytes per character
        # is a conservative upper bound, including original base64 and extracted text.
        query = select(func.count(), func.coalesce(func.sum(func.length(cast(Source.data, Text)) * 4), 0)).where(
            Source.path.like("uploads/%"), Source.status != "DO_NOT_USE")
        if subject is not None:
            query = query.where(Source.user_id == subject)
        count, size = db.execute(query).one()
        if count + 1 > count_limit or size + incoming_bytes > byte_limit:
            raise ValueError("자료 보관 한도에 도달했습니다. 필요 없는 원자료를 삭제하거나 운영자에게 문의해 주세요.")
