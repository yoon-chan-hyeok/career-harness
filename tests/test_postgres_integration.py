"""Runs against an isolated PostgreSQL service in CI, without private input or live AI."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from career.retrieval import index_embeddings, search
from career.truth import add_evidence, register_source
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URL"), reason="isolated PostgreSQL not configured")
def test_shared_budget_is_serialized_across_postgres_connections(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from career.provider_policy import BudgetExceeded, StagePolicy
    from career.service_access import configure_member
    from career.usage_limits import configure_usage, request_budget_scope, usage_status

    url = os.environ["TEST_POSTGRES_URL"]
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.delenv("DATABASE_MIGRATION_URL", raising=False)
    command.upgrade(Config("alembic.ini"), "head")
    engine = create_engine(url, pool_size=8, max_overflow=0)
    shared = "__career_test_" + str(uuid4())
    monkeypatch.setattr("career.usage_limits.SHARED_BUDGET_USER", shared)
    monkeypatch.setattr("career.service_access.SHARED_BUDGET_USER", shared)
    monkeypatch.setenv("CAREER_SHARED_SERVICE", "1")
    operator = str(uuid4())
    users = [operator, *[str(uuid4()) for _ in range(5)]]
    monkeypatch.setenv("CAREER_ADMIN_USER_IDS", operator)
    with Session(engine) as db:
        for user in users:
            configure_member(db, operator, user, "ACTIVE", {})
        configure_usage(db, shared, {"daily_calls": 1})
        db.commit()
    barrier = Barrier(len(users))

    def invoke(user):
        barrier.wait(timeout=10)
        with Session(engine) as db:
            try:
                with request_budget_scope(db, user) as quota:
                    ticket = quota.draw(StagePolicy("unknown", max_output_tokens=20), 20)
                    quota.settle_call(ticket, "unknown", {"input_tokens": 10, "output_tokens": 5})
                return True
            except BudgetExceeded:
                return False

    with ThreadPoolExecutor(max_workers=len(users)) as executor:
        assert sum(executor.map(invoke, users)) == 1
    with Session(engine) as db:
        total = usage_status(db, shared)["daily"]
        assert total["calls"] == 1 and total["tokens"] == 15 and total["reserved_calls"] == 0
        assert sum(usage_status(db, user)["daily"]["calls"] for user in users) == 1
    engine.dispose()


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URL"), reason="isolated PostgreSQL not configured")
def test_public_request_cap_is_atomic_in_postgres(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from career.public_guard import limit_request
    from fastapi import HTTPException

    url = os.environ["TEST_POSTGRES_URL"]
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.delenv("DATABASE_MIGRATION_URL", raising=False)
    command.upgrade(Config("alembic.ini"), "head")
    monkeypatch.setenv("CAREER_ACCESS_MODE", "public")
    monkeypatch.setenv("CAREER_PUBLIC_MUTATIONS_PER_MINUTE", "2")
    monkeypatch.setattr("career.public_guard.time.time", lambda: 6000)
    engine = create_engine(url, pool_size=8, max_overflow=0)
    owner = str(uuid4())
    barrier = Barrier(8)

    def call(_):
        barrier.wait(timeout=10)
        try:
            limit_request(engine, owner, "POST")
            return True
        except HTTPException as error:
            assert error.status_code == 429
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(call, range(8))) == 2
    limit_request(engine, str(uuid4()), "POST")
    engine.dispose()


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URL"), reason="isolated PostgreSQL not configured")
def test_public_account_deletion_purges_vectors_and_rejects_late_writer_in_postgres(monkeypatch):
    import httpx
    from career.account_lifecycle import delete_account
    from career.db import Record
    from career.models import AIUsageBucket, ServiceMember, Source
    from career.public_guard import bind_request
    from fastapi import HTTPException
    from sqlalchemy import select

    url = os.environ["TEST_POSTGRES_URL"]
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.delenv("DATABASE_MIGRATION_URL", raising=False)
    command.upgrade(Config("alembic.ini"), "head")
    for name, value in {
        "CAREER_ACCESS_MODE": "public", "AUTH_MODE": "supabase",
        "SUPABASE_URL": "https://synthetic.supabase.co",
        "SUPABASE_SECRET_KEY": "sb_secret_synthetic-only", "CAREER_ADMIN_USER_IDS": "",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr("career.account_lifecycle.require_recent_otp", lambda *args: None)
    engine = create_engine(url)
    own, other = str(uuid4()), str(uuid4())

    class Embedder:
        def embed(self, texts):
            return [[1.0] + [0.0] * 1535 for _ in texts]

    with Session(engine) as db:
        for user in (own, other):
            db.add(ServiceMember(user_id=user, status="ACTIVE", limits={}))
            source, _ = register_source(db, user, "synthetic", "synthetic private text", "MASTER")
            add_evidence(db, user, source.id, "합성", "실제 개인자료 없음", status="VERIFIED")
            assert index_embeddings(db, user, Embedder()) == 1
            db.add(AIUsageBucket(user_id=user, period="D:2026-10-05", data={"calls": 1}))
        db.commit()
    with Session(engine, expire_on_commit=False) as writer:
        cached = writer.get(ServiceMember, own)
        assert cached is not None
        writer.commit()
        with Session(engine) as closer:
            assert delete_account(closer, own, "DELETE", "fresh", transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={})))['auth_account_deleted']
        assert cached.status == "ACTIVE"
        bind_request(writer, own)
        writer.add(Record(user_id=own, kind="Conversation", data={"text": "late response"}))
        writer.flush()
        with pytest.raises(HTTPException):
            writer.commit()
        writer.rollback()
    with Session(engine) as db:
        assert not list(db.scalars(select(Source).where(Source.user_id == own)))
        assert len(list(db.scalars(select(Source).where(Source.user_id == other)))) == 1
        for user, count in ((own, 0), (other, 1)):
            assert db.scalar(text("SELECT count(*) FROM evidence_embeddings WHERE user_id=:user"), {"user": user}) == count
        assert db.scalar(select(AIUsageBucket).where(AIUsageBucket.user_id == own)) is not None
        assert {r.kind for r in db.scalars(select(Record).where(Record.user_id == own))} == {"AccountDeletionReceipt"}
    engine.dispose()


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URL"), reason="isolated PostgreSQL not configured")
def test_postgres_fts_semantic_episode_expression_and_user_filter(monkeypatch):
    url = os.environ["TEST_POSTGRES_URL"]
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    command.check(Config("alembic.ini"))
    engine = create_engine(url)
    with engine.connect() as connection:
        definition = connection.execute(text(
            "SELECT indexdef FROM pg_indexes WHERE schemaname='public' "
            "AND tablename='evidences' AND indexname='ix_evidence_fts'"
        )).scalar()
        assert definition and "USING gin" in definition and "to_tsvector" in definition
    user = "test-" + str(uuid4())

    class Embedder:
        def embed(self, texts):
            return [[0.0, 1.0] + [0.0] * 1534 if "판단" in t else [1.0, 0.0] + [0.0] * 1534 for t in texts]

    with Session(engine) as db:
        source, _ = register_source(db, user, "results", "fixture", "MASTER")
        target = add_evidence(
            db,
            user,
            source.id,
            "실험",
            "기준 비교",
            {"decision_episode": {"decision": "판단 기준을 바꿨다"}},
            "VERIFIED",
        )
        add_evidence(db, user, source.id, "기타", "도구 구현", status="VERIFIED")
        expression_source, _ = register_source(db, user, "application", "표현 판단", "APPLICATION")
        expression = add_evidence(db, user, expression_source.id, "표현", "표현 판단", kind="EXPRESSION")
        private_source, _ = register_source(db, "another-user", "private", "판단", "MASTER")
        add_evidence(db, "another-user", private_source.id, "비공개", "판단", status="VERIFIED")
        assert index_embeddings(db, user, Embedder()) == 3
        result = search(db, user, "판단", embedder=Embedder(), limit=1)
        assert result[0]["id"] == target.id
        assert search(db, user, "실험")[0]["id"] == target.id
        assert search(db, user, "판단", "EXPRESSION", embedder=Embedder())[0]["id"] == expression.id
        # Distinct actual outputs must broaden recall; Korean stems also match
        # inside an inflected compound instead of requiring exact FTS lexemes.
        report = add_evidence(db, user, source.id, "보고서", "분석보고서를 작성했다", status="VERIFIED")
        dashboard = add_evidence(db, user, source.id, "대시보드", "현황을 시각화했다", status="VERIFIED")
        assert {item["id"] for item in search(db, user, "보고서 대시보드")} == {report.id, dashboard.id}
        assert search(db, user, "분석보고")[0]["id"] == report.id
        assert search(db, user, "판단 기준")[0]["id"] == target.id
        assert len(search(db, user, "", limit=1)) == 1
        assert search(db, user, "없는단어") == []
    engine.dispose()


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URL"), reason="isolated PostgreSQL not configured")
def test_local_e5_pgvector_is_separate_private_and_rejects_stale_content(monkeypatch):
    from career.semantic import PROFILE_ID, IndexRequest, SearchRequest, documents, index, semantic_search
    from career.semantic_models import LocalEvidenceEmbedding
    from sqlalchemy import select

    url = os.environ["TEST_POSTGRES_URL"]
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.delenv("DATABASE_MIGRATION_URL", raising=False)
    command.upgrade(Config("alembic.ini"), "head")
    engine = create_engine(url)
    user = "local-semantic-" + str(uuid4())
    vector = [1.0] + [0.0] * 383
    with Session(engine) as db:
        source, _ = register_source(db, user, "local-e5", "합성 근거", "MASTER")
        target = add_evidence(db, user, source.id, "분석", "데이터를 검토했다", status="VERIFIED")
        document = documents(db, user)["items"][0]
        assert (
            index(
                db,
                user,
                IndexRequest.model_validate(
                    {
                        "profile_id": PROFILE_ID,
                        "items": [
                            {
                                "evidence_id": target.id,
                                "content_hash": document["content_hash"],
                                "vector": vector,
                            }
                        ],
                    }
                ),
            )["indexed"]
            == 1
        )
        request = SearchRequest(profile_id=PROFILE_ID, query="자료분석", vector=vector)
        assert semantic_search(db, user, request)["items"][0]["id"] == target.id
        assert semantic_search(db, "other-user", request)["items"] == []
        assert (
            db.scalar(select(LocalEvidenceEmbedding).where(LocalEvidenceEmbedding.user_id == user))
            is not None
        )
        target.body = "수정한 내용"
        db.flush()
        result = semantic_search(db, user, request)
        assert result["items"] == [] and result["stale_count"] == 1
        source.status = "REJECTED"
        db.flush()
        assert documents(db, user)["items"] == []
    engine.dispose()


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URL"), reason="isolated PostgreSQL not configured")
def test_supabase_data_api_roles_cannot_read_private_career_tables(monkeypatch):
    """Transaction rollback preserves the isolated CI schema; no real Supabase project is used."""
    url = os.environ["TEST_POSTGRES_URL"]
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.delenv("DATABASE_MIGRATION_URL", raising=False)
    command.upgrade(Config("alembic.ini"), "head")
    engine = create_engine(url)
    script = (Path(__file__).resolve().parents[1] / "deploy" / "supabase-security.sql").read_text(
        encoding="utf-8"
    )
    # Apply the reviewed body inside this test's transaction rather than committing it.
    script = script.replace("BEGIN;", "").replace("COMMIT;", "")
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(
                text("""DO $$ BEGIN
                IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='anon') THEN CREATE ROLE anon; END IF;
                IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='authenticated') THEN CREATE ROLE authenticated; END IF;
                END $$""")
            )
            connection.execute(text("GRANT USAGE ON SCHEMA public TO anon, authenticated"))
            connection.execute(text("GRANT ALL ON public.sources, public.service_members TO anon, authenticated"))
            connection.execute(text("ALTER TABLE public.sources DISABLE ROW LEVEL SECURITY"))
            connection.execute(text("ALTER TABLE public.service_members DISABLE ROW LEVEL SECURITY"))
            assert connection.execute(
                text("SELECT has_table_privilege('anon','public.sources','SELECT')")
            ).scalar()
            connection.exec_driver_sql(script, execution_options={"no_parameters": True})
            for role in ["anon", "authenticated"]:
                assert not connection.execute(
                    text("SELECT has_table_privilege(:role,'public.request_rate_buckets','SELECT,INSERT,UPDATE,DELETE,TRUNCATE')"),
                    {"role": role},
                ).scalar()
                assert not connection.execute(
                    text("SELECT has_table_privilege(:role,'public.service_members','SELECT,INSERT,UPDATE,DELETE,TRUNCATE')"),
                    {"role": role},
                ).scalar()
                assert not connection.execute(
                    text(
                        "SELECT has_table_privilege(:role,'public.sources','SELECT,INSERT,UPDATE,DELETE,TRUNCATE')"
                    ),
                    {"role": role},
                ).scalar()
                nested = connection.begin_nested()
                try:
                    connection.execute(text("SET LOCAL ROLE " + role))
                    with pytest.raises(ProgrammingError):
                        connection.execute(text("SELECT * FROM public.sources"))
                finally:
                    nested.rollback()
            assert connection.execute(
                text("SELECT relrowsecurity FROM pg_class WHERE oid='public.sources'::regclass")
            ).scalar()
            assert connection.execute(
                text("SELECT relrowsecurity FROM pg_class WHERE oid='public.service_members'::regclass")
            ).scalar()
            assert connection.execute(
                text("SELECT relrowsecurity FROM pg_class WHERE oid='public.request_rate_buckets'::regclass")
            ).scalar()
        finally:
            transaction.rollback()
    engine.dispose()
