"""Portable private local embeddings, separate from legacy OpenAI vector(1536)."""

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from career.db import Base, Owned


class LocalEvidenceEmbedding(Owned, Base):
    __tablename__ = "local_evidence_embeddings"
    __table_args__ = (
        UniqueConstraint("user_id", "evidence_id", "profile_id", name="uq_local_evidence_embedding"),
    )
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidences.id", ondelete="CASCADE"), index=True)
    profile_id: Mapped[str] = mapped_column(String(100), index=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    embedding: Mapped[list[float]] = mapped_column(JSON().with_variant(Vector(384), "postgresql"))
