import os
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv
from sqlalchemy import JSON, DateTime, String, create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

if os.getenv("CAREER_SERVERLESS_RUNTIME") != "1":
    load_dotenv()


def uid() -> str:
    return str(uuid4())


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Owned:
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Record(Owned, Base):
    """Typed auxiliary domain records; primary workflow entities have dedicated tables."""

    __tablename__ = "domain_records"
    kind: Mapped[str] = mapped_column(String(64), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


def database_url(url: str) -> URL:
    """Provider dashboard URLs use postgres/postgresql; the installed driver is psycopg 3."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url.removeprefix("postgres://")
    parsed = make_url(url)
    if parsed.drivername in {"postgres", "postgresql"}:
        parsed = parsed.set(drivername="postgresql+psycopg")
    return parsed


def make_engine(url: str | None = None):
    parsed = database_url(url or os.getenv("DATABASE_URL", "sqlite:///./career.db"))
    if parsed.get_backend_name() == "sqlite":
        return create_engine(parsed, connect_args={"check_same_thread": False}, pool_pre_ping=True)
    connect_args: dict[str, Any] = {"connect_timeout": 10}
    if os.getenv("DATABASE_POOL_MODE", "session") == "transaction":
        # Transaction poolers cannot preserve psycopg's prepared statement session state.
        connect_args["prepare_threshold"] = None
    return create_engine(
        parsed,
        connect_args=connect_args,
        pool_pre_ping=True,
        pool_size=int(os.getenv("DATABASE_POOL_SIZE", "5")),
        max_overflow=int(os.getenv("DATABASE_MAX_OVERFLOW", "5")),
        pool_recycle=1800,
        pool_timeout=10,
    )


engine = make_engine()
SessionLocal = sessionmaker(engine, expire_on_commit=False)
