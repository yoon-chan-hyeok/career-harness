"""Device-side E5 vectors: this server never sends text to an embedding provider."""

import hashlib
import json
import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import bindparam, select, text
from sqlalchemy.orm import Session

from career.models import Evidence, Source
from career.retrieval import search, task_rerank
from career.semantic_models import LocalEvidenceEmbedding
from career.truth import view
from career.validation import GOOD

MODEL_ID = "Xenova/multilingual-e5-small"
MODEL_REVISION = "761b726dd34fb83930e26aab4e9ac3899aa1fa78"
DIMENSIONS = 384
PROFILE = {
    "model_id": MODEL_ID,
    "revision": MODEL_REVISION,
    "dtype": "q8",
    "dimensions": DIMENSIONS,
    "pooling": "mean",
    "normalize": True,
    "query_prefix": "query: ",
    "passage_prefix": "passage: ",
    "max_tokens": 512,
    "max_text_chars": 6000,
    "format_version": 1,
}
PROFILE_ID = (
    "multilingual-e5-small-q8-"
    + hashlib.sha256(json.dumps(PROFILE, sort_keys=True).encode()).hexdigest()[:20]
)
StoreKind = Literal["FACT", "EXPRESSION"]
MAX_SEARCH_ITEMS = 5000


class IndexItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_id: Annotated[str, Field(min_length=1, max_length=64)]
    content_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    vector: Annotated[list[float], Field(min_length=DIMENSIONS, max_length=DIMENSIONS)]

    @field_validator("vector")
    @classmethod
    def finite_nonzero(cls, vector):
        return normalize_vector(vector)


class IndexRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_id: Annotated[str, Field(max_length=100)]
    items: Annotated[list[IndexItem], Field(max_length=32)]


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_id: Annotated[str, Field(max_length=100)]
    query: Annotated[str, Field(max_length=4000)]
    vector: Annotated[list[float], Field(min_length=DIMENSIONS, max_length=DIMENSIONS)]
    kind: StoreKind = "FACT"
    limit: Annotated[int, Field(ge=1, le=100)] = 12
    task_context: dict | None = None

    @field_validator("vector")
    @classmethod
    def finite_nonzero(cls, vector):
        return normalize_vector(vector)


def normalize_vector(vector: list[float]) -> list[float]:
    if len(vector) != DIMENSIONS or any(not math.isfinite(value) for value in vector):
        raise ValueError("384차원의 유한한 벡터가 필요합니다.")
    norm = math.sqrt(sum(value * value for value in vector))
    if not math.isfinite(norm) or norm < 1e-12:
        raise ValueError("빈 벡터는 저장하거나 검색할 수 없습니다.")
    return [float(value / norm) for value in vector]


def profile_info():
    return {
        **PROFILE,
        "profile_id": PROFILE_ID,
        "execution": "device",
        "weight_bytes": 118308185,
        "provider_calls": False,
        "source_url": "https://huggingface.co/Xenova/multilingual-e5-small",
    }


def _eligible(db: Session, user: str, kind: StoreKind | None = None):
    statement = (
        select(Evidence, Source)
        .join(Source, Source.id == Evidence.source_id)
        .where(Evidence.user_id == user, Source.user_id == user, Source.status.in_(GOOD))
    )
    if kind == "EXPRESSION":
        return statement.where(Evidence.kind == "EXPRESSION")
    if kind == "FACT":
        return statement.where(Evidence.kind != "EXPRESSION", Evidence.status.in_(GOOD))
    return statement.where((Evidence.kind == "EXPRESSION") | Evidence.status.in_(GOOD))


def content(item: Evidence, source: Source):
    passage = (
        item.title
        + "\n"
        + item.body
        + "\n"
        + json.dumps(item.data.get("decision_episode", {}), ensure_ascii=False, sort_keys=True)
    )[: PROFILE["max_text_chars"]]
    canonical = {
        "evidence_id": item.id,
        "source_id": source.id,
        "source_hash": source.content_hash,
        "source_status": source.status,
        "kind": item.kind,
        "status": item.status,
        "title": item.title,
        "body": item.body,
        "data": item.data,
        "passage": passage,
    }
    digest = hashlib.sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return passage, digest


def documents(db: Session, user: str, kind: StoreKind = "FACT", cursor: str | None = None):
    if kind not in {"FACT", "EXPRESSION"}:
        raise ValueError("자료 유형을 확인해 주세요.")
    if cursor and len(cursor) > 64:
        raise ValueError("목록 위치를 확인해 주세요.")
    statement = _eligible(db, user, kind).order_by(Evidence.id).limit(33)
    if cursor:
        statement = statement.where(Evidence.id > cursor)
    rows = db.execute(statement).all()
    selected = rows[:32]
    identifiers = [item.id for item, _source in selected]
    indexed = {
        row.evidence_id: row.content_hash
        for row in db.scalars(
            select(LocalEvidenceEmbedding).where(
                LocalEvidenceEmbedding.user_id == user,
                LocalEvidenceEmbedding.profile_id == PROFILE_ID,
                LocalEvidenceEmbedding.evidence_id.in_(identifiers),
            )
        )
    }
    items = []
    for item, source in selected:
        passage, digest = content(item, source)
        items.append(
            {
                "evidence_id": item.id,
                "title": item.title,
                "text": passage,
                "content_hash": digest,
                "indexed": indexed.get(item.id) == digest,
            }
        )
    return {
        "profile": profile_info(),
        "items": items,
        "next_cursor": selected[-1][0].id if len(rows) > 32 else None,
    }


def _profile(ident: str):
    if ident != PROFILE_ID:
        raise ValueError("검색 모델이 변경되었습니다. 현재 모델로 색인을 다시 만들어 주세요.")


def index(db: Session, user: str, request: IndexRequest):
    _profile(request.profile_id)
    identifiers = [item.evidence_id for item in request.items]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("같은 근거가 중복되었습니다.")
    available = {
        item.id: (item, source)
        for item, source in db.execute(_eligible(db, user).where(Evidence.id.in_(identifiers)))
    }
    if set(identifiers) != set(available):
        raise ValueError("현재 확인된 본인 자료만 색인할 수 있습니다.")
    existing = {
        row.evidence_id: row
        for row in db.scalars(
            select(LocalEvidenceEmbedding).where(
                LocalEvidenceEmbedding.user_id == user,
                LocalEvidenceEmbedding.profile_id == PROFILE_ID,
                LocalEvidenceEmbedding.evidence_id.in_(identifiers),
            )
        )
    }
    saved = stale = 0
    for supplied in request.items:
        item, source = available[supplied.evidence_id]
        _, digest = content(item, source)
        if digest != supplied.content_hash:
            stale += 1
            continue
        row = existing.get(item.id)
        if row is None:
            row = LocalEvidenceEmbedding(
                user_id=user,
                evidence_id=item.id,
                profile_id=PROFILE_ID,
                content_hash=digest,
                embedding=supplied.vector,
            )
            db.add(row)
        else:
            row.content_hash = digest
            row.embedding = supplied.vector
        saved += 1
    db.flush()
    return {"indexed": saved, "stale_skipped": stale, "profile_id": PROFILE_ID}


def semantic_search(db: Session, user: str, request: SearchRequest):
    _profile(request.profile_id)
    if not request.query.strip():
        return {
            "items": search(
                db, user, "", request.kind, limit=request.limit, task_context=request.task_context
            ),
            "semantic_used": False,
            "indexed_count": 0,
            "stale_count": 0,
            "profile_id": PROFILE_ID,
        }
    # Validate current truth/source hashes before distance ranking, so an obsolete
    # high-similarity vector never displaces a current candidate.
    rows = db.execute(
        _eligible(db, user, request.kind)
        .add_columns(LocalEvidenceEmbedding)
        .join(LocalEvidenceEmbedding, LocalEvidenceEmbedding.evidence_id == Evidence.id)
        .where(LocalEvidenceEmbedding.user_id == user, LocalEvidenceEmbedding.profile_id == PROFILE_ID)
        .limit(MAX_SEARCH_ITEMS + 1)
    ).all()
    if len(rows) > MAX_SEARCH_ITEMS:
        raise ValueError("검색 자료가 5,000개를 넘었습니다. 자료를 나눈 뒤 검색해 주세요.")
    valid = {}
    stale = 0
    for item, source, vector_row in rows:
        _, digest = content(item, source)
        if digest != vector_row.content_hash:
            stale += 1
            continue
        try:
            vector = normalize_vector(list(vector_row.embedding))
        except (ValueError, TypeError):
            stale += 1
            continue
        valid[item.id] = (item, vector)
    if db.bind is not None and db.bind.dialect.name == "postgresql" and valid:
        identifiers = db.scalars(
            text(
                "SELECT evidence_id FROM local_evidence_embeddings WHERE user_id=:user "
                "AND profile_id=:profile AND evidence_id IN :ids "
                "ORDER BY embedding <=> CAST(:vector AS vector), evidence_id LIMIT :n"
            ).bindparams(bindparam("ids", expanding=True)),
            {
                "user": user,
                "profile": PROFILE_ID,
                "ids": list(valid),
                "vector": str(request.vector),
                "n": min(request.limit * 4, 200),
            },
        ).all()
        ranked = [
            (ident, sum(a * b for a, b in zip(valid[ident][1], request.vector, strict=True)))
            for ident in identifiers
        ]
    else:
        ranked = sorted(
            (
                (ident, sum(a * b for a, b in zip(vector, request.vector, strict=True)))
                for ident, (_item, vector) in valid.items()
            ),
            key=lambda pair: (-pair[1], pair[0]),
        )
        ranked = ranked[: min(request.limit * 4, 200)]
    items = [
        {
            **view(valid[ident][0]),
            "semantic_metadata": {
                "similarity": round(max(-1.0, min(1.0, score)), 6),
                "profile_id": PROFILE_ID,
                "basis": "SIMILARITY_NOT_DIRECT_FIT_OR_FACT_PROOF",
            },
        }
        for ident, score in ranked
    ]
    return {
        "items": task_rerank(items, request.task_context, request.limit),
        "semantic_used": bool(valid),
        "indexed_count": len(valid),
        "stale_count": stale,
        "profile_id": PROFILE_ID,
    }
