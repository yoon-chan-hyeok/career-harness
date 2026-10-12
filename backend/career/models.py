from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from career import (
    entities,  # noqa: F401
    projections,  # noqa: F401
    semantic_models,  # noqa: F401
    upgrade_models,  # noqa: F401
)
from career.db import Base, Owned, now


class Source(Owned, Base):
    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("user_id", "path", "content_hash"),)
    path: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    authority: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30), default="SOURCE_BACKED")
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Fact(Owned, Base):
    __tablename__ = "career_facts"
    key: Mapped[str] = mapped_column(String(200), index=True)
    fact_type: Mapped[str] = mapped_column(String(40))
    value: Mapped[dict[str, Any]] = mapped_column(JSON)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="SOURCE_BACKED")
    supersedes_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Evidence(Owned, Base):
    __tablename__ = "evidences"
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(40), default="EVIDENCE")
    status: Mapped[str] = mapped_column(String(30), default="UNVERIFIED")
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Artifact(Owned, Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        UniqueConstraint("user_id", "workspace_id", "kind", "slot", "version", name="uq_artifact_version"),
    )
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(50))
    slot: Mapped[str] = mapped_column(String(100), default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE")
    depends_on: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    prompt_version: Mapped[str] = mapped_column(String(50), default="v1")
    model_version: Mapped[str] = mapped_column(String(100), default="manual")


class Workspace(Owned, Base):
    __tablename__ = "application_workspaces"
    company: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(200))
    jd_raw: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(40), default="CREATED")
    mode: Mapped[str] = mapped_column(String(20), default="GUIDED")
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Feedback(Owned, Base):
    __tablename__ = "artifact_feedback_events"
    application_id: Mapped[str] = mapped_column(String(64), index=True)
    artifact_id: Mapped[str] = mapped_column(String(64))
    artifact_version: Mapped[int] = mapped_column(Integer)
    stage: Mapped[str] = mapped_column(String(60))
    action: Mapped[str] = mapped_column(String(20))
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Revision(Owned, Base):
    __tablename__ = "document_revision_events"
    application_id: Mapped[str] = mapped_column(String(64), index=True)
    document_type: Mapped[str] = mapped_column(String(40))
    from_version: Mapped[int] = mapped_column(Integer)
    to_version: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)


class PromptRun(Owned, Base):
    __tablename__ = "prompt_runs"
    stage: Mapped[str] = mapped_column(String(60))
    provider: Mapped[str] = mapped_column(String(60))
    data: Mapped[dict[str, Any]] = mapped_column(JSON)


class ExecutionRun(Owned, Base):
    """Durable, user-owned request execution; no invented agent progress."""

    __tablename__ = "execution_runs"
    __table_args__ = (
        UniqueConstraint("user_id", "workspace_id", "active_key", name="uq_execution_active"),
    )
    workspace_id: Mapped[str] = mapped_column(ForeignKey("application_workspaces.id"), index=True)
    action: Mapped[str] = mapped_column(String(60))
    label: Mapped[str] = mapped_column(String(150))
    status: Mapped[str] = mapped_column(String(30), default="RUNNING")
    active_key: Mapped[str | None] = mapped_column(String(20), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    message: Mapped[str] = mapped_column(String(300), default="")
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AIUsageSettings(Owned, Base):
    __tablename__ = "ai_usage_settings"
    __table_args__ = (UniqueConstraint("user_id", name="uq_ai_usage_settings_user"),)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ServiceMember(Base):
    """Operator-controlled access and ceilings; contains no application content."""

    __tablename__ = "service_members"
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    limits: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AIUsageBucket(Owned, Base):
    __tablename__ = "ai_usage_buckets"
    __table_args__ = (UniqueConstraint("user_id", "period", name="uq_ai_usage_bucket_period"),)
    period: Mapped[str] = mapped_column(String(16))
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class RequestRateBucket(Base):
    """One current window per account, shared by all API workers."""

    __tablename__ = "request_rate_buckets"
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    minute: Mapped[int] = mapped_column(Integer)
    requests: Mapped[int] = mapped_column(Integer)
    mutations: Mapped[int] = mapped_column(Integer)


class AIUsageReservation(Owned, Base):
    __tablename__ = "ai_usage_reservations"
    status: Mapped[str] = mapped_column(String(20), default="RESERVED")
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
