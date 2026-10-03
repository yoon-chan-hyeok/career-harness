"""Account-scoped recovery text. A draft never confers approval or truth status."""

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from career.artifacts import latest
from career.db import now
from career.models import Artifact, Workspace
from career.truth import owned
from career.upgrade_models import EditorDraft

TEXT_KINDS = {
    "text", "textarea", "number", "select-one", "select-multiple", "email", "url", "search",
    "date", "month", "datetime-local", "time", "tel", "week",
}
SENSITIVE = re.compile(r"password|token|api.?key|secret|confirm|approv|consent|agreement", re.I)


class DraftField(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str = Field(max_length=100000)
    kind: str

    @field_validator("kind")
    @classmethod
    def text_only(cls, value: str):
        if value not in TEXT_KINDS:
            raise ValueError("텍스트 편집 내용만 임시 저장할 수 있습니다.")
        return value


class DraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payload: dict[str, DraftField]
    base_artifact_id: str | None = Field(default=None, max_length=64)
    workspace_id: str | None = Field(default=None, max_length=64)

    @field_validator("payload")
    @classmethod
    def bounded_safe_fields(cls, value):
        if len(value) > 100 or len(json.dumps({k: v.model_dump() for k, v in value.items()})) > 500000:
            raise ValueError("임시 편집 내용의 크기를 줄여 주세요.")
        if any(len(key) > 200 or SENSITIVE.search(key) for key in value):
            raise ValueError("키·비밀번호·승인 확인은 임시 저장할 수 없습니다.")
        return value


def _find(db: Session, user: str, key: str):
    if not key.strip() or len(key) > 200 or SENSITIVE.search(key):
        raise ValueError("유효한 편집 창을 선택해 주세요.")
    return db.scalar(select(EditorDraft).where(EditorDraft.user_id == user, EditorDraft.key == key))


def _is_stale(db: Session, user: str, base: Artifact | None):
    if base is None:
        return False
    current = latest(db, user, base.workspace_id, base.kind, base.slot, required=False)
    return base.status not in {"ACTIVE", "LOCKED"} or current is None or current.id != base.id


def read_draft(db: Session, user: str, key: str) -> dict[str, Any]:
    row = _find(db, user, key)
    if row is None:
        raise LookupError("임시 저장 내용이 없습니다.")
    base = owned(db, Artifact, user, row.base_artifact_id) if row.base_artifact_id else None
    return {
        "key": row.key, "payload": row.payload, "workspace_id": row.workspace_id,
        "base_artifact_id": row.base_artifact_id, "updated_at": row.updated_at,
        "stale_base": _is_stale(db, user, base),
    }


def save_draft(db: Session, user: str, key: str, body: DraftRequest):
    row = _find(db, user, key)
    if body.workspace_id:
        owned(db, Workspace, user, body.workspace_id)
    base = owned(db, Artifact, user, body.base_artifact_id) if body.base_artifact_id else None
    if base and (body.workspace_id != base.workspace_id or _is_stale(db, user, base)):
        raise ValueError("문서 버전이 바뀌었습니다. 현재 문서를 다시 열고 편집 내용을 비교해 주세요.")
    if row and row.base_artifact_id != body.base_artifact_id:
        raise ValueError("다른 버전의 임시 편집 내용이 있습니다. 복구 또는 삭제한 뒤 다시 저장해 주세요.")
    if row is None:
        row = EditorDraft(user_id=user, key=key)
        db.add(row)
    row.workspace_id = body.workspace_id
    row.base_artifact_id = body.base_artifact_id
    row.payload = {key: field.model_dump() for key, field in body.payload.items()}
    row.updated_at = now()
    db.flush()
    return read_draft(db, user, key)


def delete_draft(db: Session, user: str, key: str):
    if row := _find(db, user, key):
        db.delete(row)
    return {"deleted": True}
