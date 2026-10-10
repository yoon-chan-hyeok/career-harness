"""Cross-worker public request limits and a final fence against revoked writers."""

import time

from fastapi import HTTPException
from sqlalchemy import case, event, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from career.models import Artifact, Evidence, RequestRateBucket, Source, Workspace
from career.production import integer_setting
from career.service_access import SHARED_BUDGET_USER, access_mode, require_member, shared_service


def limit_request(bind, user: str, method: str = "GET"):
    if access_mode() != "public":
        return
    total = integer_setting("CAREER_PUBLIC_REQUESTS_PER_MINUTE", 120, 1, 10000)
    writes = integer_setting("CAREER_PUBLIC_MUTATIONS_PER_MINUTE", 20, 1, 1000)
    minute = int(time.time() // 60)
    mutation = int(method not in {"GET", "HEAD", "OPTIONS"})
    with Session(bind) as ledger, ledger.begin():
        insert = sqlite_insert if bind.dialect.name == "sqlite" else pg_insert
        table = RequestRateBucket
        old = table.minute == minute
        statement = insert(table).values(user_id=user, minute=minute, requests=1, mutations=mutation)
        statement = statement.on_conflict_do_update(
            index_elements=["user_id"],
            set_={"minute": minute, "requests": case((old, table.requests + 1), else_=1),
                  "mutations": case((old, table.mutations + mutation), else_=mutation)},
            where=(~old | ((table.requests < total) & (table.mutations + mutation <= writes))),
        ).returning(table.user_id)
        if ledger.scalar(statement) is None:
            raise HTTPException(429, "요청이 많습니다. 잠시 후 다시 시도해 주세요.",
                                headers={"Retry-After": str(60 - int(time.time()) % 60)})


def bind_request(db: Session, user: str):
    db.info["career_request_user"] = user


@event.listens_for(Session, "before_flush")
def _track_orm_writes(db, _context, _instances):
    if db.info.get("career_request_user") and (db.new or db.dirty or db.deleted):
        db.info["career_request_wrote"] = True
        models = db.info.setdefault("career_request_models", set())
        models.update(type(row) for row in db.new)


@event.listens_for(Session, "do_orm_execute")
def _track_bulk_writes(state):
    if state.session.info.get("career_request_user") and (state.is_insert or state.is_update or state.is_delete):
        state.session.info["career_request_wrote"] = True


def fence_commit(db: Session):
    user = db.info.get("career_request_user")
    if not user or not shared_service() or db.info.get("career_lifecycle_exempt"):
        return
    if not (db.info.get("career_request_wrote") or db.new or db.dirty or db.deleted):
        return
    from career.usage_limits import _settings

    with db.no_autoflush:
        _settings(db, SHARED_BUDGET_USER, lock=True)
        require_member(db, user)
    if access_mode() != "public":
        return
    models = db.info.get("career_request_models", set()) | {type(row) for row in db.new}
    # Check after flush so a transaction creating multiple rows is counted exactly.
    db.flush()
    for model, setting, default in (
        (Workspace, "CAREER_PUBLIC_MAX_APPLICATIONS", 100),
        (Evidence, "CAREER_PUBLIC_MAX_EVIDENCE", 500),
        (Source, "CAREER_PUBLIC_MAX_SOURCES", 500),
        (Artifact, "CAREER_PUBLIC_MAX_ARTIFACTS", 5000),
    ):
        if model not in models:
            continue
        maximum = integer_setting(setting, default, 1, 100000)
        count = db.scalar(select(func.count()).select_from(model).where(model.user_id == user)) or 0
        if count > maximum:
            raise HTTPException(409, "자료 보관 한도에 도달했습니다. 기존 자료를 정리한 뒤 다시 시도해 주세요.")


@event.listens_for(Session, "before_commit")
def _fence_public_writes(db):
    # SAVEPOINT releases are not the final transaction boundary.
    if not db.in_nested_transaction():
        fence_commit(db)


@event.listens_for(Session, "after_transaction_end")
def _clear_write_tracking(db, transaction):
    if transaction.parent is None:
        db.info.pop("career_request_wrote", None)
        db.info.pop("career_request_models", None)
