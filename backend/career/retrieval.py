import json
import re
from typing import Any, Protocol

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from career.models import Evidence, Source
from career.truth import view
from career.validation import GOOD


def configured_embedder(db: Session):
    import os

    from career.provider_config import provider_settings
    from career.providers import OpenAIProvider

    if (
        db.bind is not None
        and db.bind.dialect.name == "postgresql"
        and provider_settings().provider == "openai"
        and os.getenv("OPENAI_API_KEY")
        and os.getenv("OPENAI_MODEL")
    ):
        return OpenAIProvider()
    return None


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


def search(
    db: Session,
    user: str,
    query: str,
    kind="FACT",
    embedder: Embedder | None = None,
    limit=12,
    *,
    task_context=None,
    local_vector: list[float] | None = None,
    local_profile_id: str | None = None,
):
    limit = max(1, min(int(limit), 100))
    pool_limit = min(limit * 4, 200) if task_context or local_vector is not None else limit
    # One missing job-output term must not exclude otherwise relevant experience.
    # Bound the query before building expressions and use bound parameters throughout.
    tokens = list(dict.fromkeys(re.findall(r"[\w가-힣]+", query[:4000].lower())))[:32]
    tokens = [token[:80] for token in tokens]
    base = (
        select(Evidence)
        .join(Source, Source.id == Evidence.source_id)
        .where(Evidence.user_id == user, Source.user_id == user, Source.status.in_(GOOD))
    )
    base = (
        base.where(Evidence.kind == "EXPRESSION")
        if kind == "EXPRESSION"
        else base.where(Evidence.kind != "EXPRESSION", Evidence.status.in_(GOOD))
    )
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        store_filter = (
            "e.kind = 'EXPRESSION'"
            if kind == "EXPRESSION"
            else "e.kind <> 'EXPRESSION' AND e.status IN ('VERIFIED','USER_CONFIRMED','SOURCE_BACKED')"
        )
        searchable = "(e.title || ' ' || e.body || ' ' || COALESCE((e.data->'decision_episode')::text, ''))"
        parameters: dict[str, Any] = {"user": user, "n": pool_limit}
        if tokens:
            # Sanitized word tokens cannot introduce tsquery operators. Quote each
            # lexeme anyway, and combine with OR instead of plainto_tsquery's AND.
            parameters["tsq"] = " | ".join("'" + token.replace("'", "''") + "'" for token in tokens)
            partials = []
            match_scores = []
            for index, token in enumerate(tokens):
                key = f"token_{index}"
                parameters[key] = "%" + token.replace("\\", "\\\\").replace("_", "\\_") + "%"
                partials.append(f"{searchable} ILIKE :{key} ESCAPE '\\'")
                match_scores.append(f"CASE WHEN {partials[-1]} THEN 1 ELSE 0 END")
            lexical_filter = (
                f"AND (to_tsvector('simple', {searchable}) @@ to_tsquery('simple', :tsq)"
                + " OR "
                + " OR ".join(partials)
                + ")"
            )
            order = (
                "(" + " + ".join(match_scores) + ") DESC, "
                f"ts_rank(to_tsvector('simple', {searchable}), to_tsquery('simple', :tsq)) DESC, "
            )
        else:
            lexical_filter = ""
            order = ""
        rows = (
            db.execute(
                text(
                    """SELECT e.id FROM evidences e JOIN sources s ON s.id=e.source_id
          WHERE e.user_id=:user AND s.user_id=:user AND """
                    + store_filter
                    + """
          AND s.status IN ('VERIFIED','USER_CONFIRMED','SOURCE_BACKED')
          """
                    + lexical_filter
                    + " ORDER BY "
                    + order
                    + "e.created_at DESC, e.id LIMIT :n"
                ),
                parameters,
            )
            .scalars()
            .all()
        )
        if embedder and tokens:
            vector = str(embedder.embed([query])[0])
            semantic = (
                db.execute(
                    text(
                        """SELECT e.id FROM evidence_embeddings v JOIN evidences e ON e.id=v.evidence_id
              JOIN sources s ON s.id=e.source_id WHERE v.user_id=:user AND e.user_id=:user AND s.user_id=:user
              AND s.status IN ('VERIFIED','USER_CONFIRMED','SOURCE_BACKED')
              AND """
                        + store_filter
                        + """ ORDER BY v.embedding <=> CAST(:vector AS vector) LIMIT :n"""
                    ),
                    {"user": user, "vector": vector, "n": pool_limit},
                )
                .scalars()
                .all()
            )
            scores = {}
            for ranking in [rows, semantic]:
                for rank, ident in enumerate(ranking):
                    scores[ident] = scores.get(ident, 0) + 1 / (60 + rank)
            rows = sorted(scores, key=lambda i: scores[i], reverse=True)
        by_id = {e.id: e for e in db.scalars(base.where(Evidence.id.in_(rows)))} if rows else {}
        return _local_fusion(
            db,
            user,
            query,
            kind,
            [view(by_id[i]) for i in rows if i in by_id],
            local_vector,
            local_profile_id,
            task_context,
            limit,
        )
    # Honest lexical fallback: no fabricated semantic embeddings when offline.
    items = list(db.scalars(base.order_by(Evidence.created_at.desc(), Evidence.id)))
    ranked = sorted(
        items,
        key=lambda e: sum(
            t
            in (
                e.title
                + " "
                + e.body
                + " "
                + json.dumps(e.data.get("decision_episode", {}), ensure_ascii=False)
            ).lower()
            for t in tokens
        ),
        reverse=True,
    )
    candidates = [
        view(e)
        for e in ranked
        if not tokens
        or any(
            t
            in (
                e.title
                + " "
                + e.body
                + " "
                + json.dumps(e.data.get("decision_episode", {}), ensure_ascii=False)
            ).lower()
            for t in tokens
        )
    ]
    return _local_fusion(
        db,
        user,
        query,
        kind,
        candidates[:pool_limit],
        local_vector,
        local_profile_id,
        task_context,
        limit,
    )


def _local_fusion(db, user, query, kind, lexical, vector, profile_id, context, limit):
    if vector is None or not query.strip():
        return task_rerank(lexical, context, limit)
    if not profile_id:
        raise ValueError("기기 검색 모델 정보를 함께 전달해 주세요.")
    # Lazy import keeps the portable lexical path independent and avoids a cycle:
    # blank semantic queries call ordinary search without an embedding vector.
    from career.semantic import SearchRequest, semantic_search

    result = semantic_search(
        db,
        user,
        SearchRequest(
            profile_id=profile_id,
            query=query,
            vector=vector,
            kind=kind,
            limit=min(limit * 4, 100),
        ),
    )
    if not result["semantic_used"]:
        return task_rerank(lexical, context, limit)
    scores = {}
    items = {}
    for ranking in [lexical, result["items"]]:
        for rank, item in enumerate(ranking):
            ident = item["id"]
            scores[ident] = scores.get(ident, 0) + 1 / (60 + rank)
            items[ident] = {**items.get(ident, {}), **item}
    fused = [items[ident] for ident in sorted(scores, key=lambda ident: (-scores[ident], ident))]
    return task_rerank(fused, context, limit)


def task_rerank(items, context, limit):
    if not context:
        return items[:limit]
    outputs = set(context.get("actual_outputs", []))
    skills = set(context.get("main_skills", []))
    question_type = context.get("question_type", "")
    decision_fields = {
        "CHALLENGE": ("unexpected_result", "reframe", "reduced_claim"),
        "JOB_COMPETENCY": ("decision", "experiment", "validation"),
        "COLLABORATION": ("constraint", "options", "observation"),
    }.get(question_type, ("decision", "observation"))

    def metadata(item):
        data = item.get("data", {})
        episode = data.get("decision_episode", {})
        episode = episode if isinstance(episode, dict) else {}
        ownership = data.get("ownership", {})
        # Uploaded evidence can retain the explicit UNKNOWN sentinel until the
        # user's contribution is confirmed; it is not a structured ownership map.
        ownership = ownership if isinstance(ownership, dict) else {}
        return {
            "explicit_output_matches": len(outputs & set(data.get("job_outputs", []))),
            "explicit_main_skill_matches": len(skills & set(data.get("main_skills", []))),
            "decision_material_fields": sum(bool(episode.get(key)) for key in decision_fields),
            "ownership_known": ownership.get("implementation", "UNKNOWN") not in {None, "", "UNKNOWN"},
            "basis": "RETRIEVAL_PRIORITY_NOT_DIRECT_FIT_OR_FACT_PROOF",
        }

    ranked = [{**item, "retrieval_metadata": metadata(item)} for item in items]
    ranked.sort(
        key=lambda item: tuple(
            -int(item["retrieval_metadata"][key])
            for key in (
                "explicit_output_matches",
                "explicit_main_skill_matches",
                "decision_material_fields",
                "ownership_known",
            )
        )
    )
    return ranked[:limit]


def index_embeddings(db: Session, user: str, embedder: Embedder):
    if db.bind is None or db.bind.dialect.name != "postgresql":
        raise ValueError("의미 검색 색인은 PostgreSQL 연결이 필요합니다.")
    items = list(
        db.scalars(
            select(Evidence)
            .join(Source, Source.id == Evidence.source_id)
            .where(
                Evidence.user_id == user,
                Source.user_id == user,
                Source.status.in_(GOOD),
                (Evidence.status.in_(GOOD) | (Evidence.kind == "EXPRESSION")),
            )
        )
    )
    vectors = (
        embedder.embed(
            [
                e.body + "\n" + json.dumps(e.data.get("decision_episode", {}), ensure_ascii=False)
                for e in items
            ]
        )
        if items
        else []
    )
    for item, vector in zip(items, vectors, strict=True):
        if len(vector) != 1536:
            raise ValueError("Embedding dimension must be 1536")
        db.execute(
            text(
                "INSERT INTO evidence_embeddings (evidence_id,user_id,embedding) VALUES (:id,:user,CAST(:v AS vector)) ON CONFLICT (evidence_id) DO UPDATE SET embedding=EXCLUDED.embedding"
            ),
            {"id": item.id, "user": user, "v": str(vector)},
        )
    return len(items)


def style_projection(_expression: dict):
    # A fixed safe vocabulary deliberately excludes copied facts, numbers and names.
    text_value = str(_expression.get("body", _expression.get("accepted_text", "")))
    sentences = [s for s in re.split(r"[.!?。\n]", text_value) if s.strip()]
    logic_vocabulary = {"관찰", "판단", "행동", "근거", "상황", "제약", "문제", "결과", "배운 점"}
    requested = _expression.get(
        "logic_pattern", _expression.get("data", {}).get("original", {}).get("logic_pattern", [])
    )
    patterns = [s for s in requested if s in logic_vocabulary]
    return {
        "logic_pattern": patterns or ["관찰", "판단", "행동", "근거"],
        "tone": [
            "짧은 문장" if sentences and sum(map(len, sentences)) / len(sentences) < 70 else "설명 중심",
            "담백함",
        ],
        "preferred_patterns": [],
        "avoid_patterns": ["추상적 선언", "기술 나열"],
    }


def compile_context(
    stage: str, *, jd="", question="", draft="", strategy=None, brief=None, evidence=None
) -> dict[str, Any]:
    if stage == "recruiter":
        return {"jd": jd, "question": question, "draft": draft}
    if stage == "writer":
        chosen = set((brief or {}).get("evidence_ids", []))
        selected = [e for e in evidence or [] if e["id"] in chosen and e["status"] in GOOD]
        if chosen != {e["id"] for e in selected}:
            raise ValueError("선택 근거의 검증 상태를 확인해 주세요.")
        return {"strategy": strategy, "brief": brief, "evidence": selected}
    return {"brief": brief, "evidence": evidence or [], "draft": draft}
