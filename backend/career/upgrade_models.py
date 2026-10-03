"""Private editor recovery metadata; never workflow truth or approval."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from career.db import Base, Owned, now


class EditorDraft(Owned, Base):
    __tablename__ = "editor_drafts"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_editor_draft_key"),)
    key: Mapped[str] = mapped_column(String(200))
    workspace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    base_artifact_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
