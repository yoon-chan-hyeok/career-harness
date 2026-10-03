from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_upgrade_downgrade_roundtrip(tmp_path: Path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    engine = create_engine(url)
    assert "users" in inspect(engine).get_table_names()
    command.check(config)
    command.downgrade(config, "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]
    command.upgrade(config, "head")
    engine.dispose()


def test_existing_history_backfilled_without_changing_bundle(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    from career.db import Record
    from career.models import Artifact, Evidence, Source, Workspace
    from career.projections import ApplicationQuestion, DraftVersion, SelectionOutcome, SubmissionSnapshot
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    url = f"sqlite:///{tmp_path / 'existing.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "0005")
    engine = create_engine(url)
    frozen = datetime.now(UTC).isoformat()
    with Session(engine) as db:
        source = Source(user_id="a", path="test", content_hash="test", authority="MASTER")
        ws = Workspace(
            user_id="a",
            company="회사",
            role="직무",
            jd_raw="공고",
            state="SUBMITTED",
            data={
                "questions": [{"id": "q", "text": "질문", "limit": 500}],
                "question_states": {"q": "FINAL_LOCKED"},
                "submitted_at": frozen,
            },
        )
        db.add_all([source, ws])
        db.flush()
        evidence = Evidence(user_id="a", source_id=source.id, title="근거", body="본문", status="VERIFIED")
        db.add(evidence)
        db.flush()
        draft = Artifact(
            user_id="a",
            workspace_id=ws.id,
            kind="Draft",
            slot="q",
            version=1,
            status="LOCKED",
            data={"text": "본문"},
            source_ids=[source.id],
        )
        snapshot = {"frozen_at": frozen, "submitted_at": None, "artifacts": []}
        bundle = Artifact(
            user_id="a", workspace_id=ws.id, kind="SubmissionBundle", status="LOCKED", data=snapshot
        )
        db.add_all(
            [
                draft,
                bundle,
                Record(
                    user_id="a",
                    kind="SelectionOutcome",
                    data={"workspace_id": ws.id, "result": "DOCUMENT_PASS", "notes": ""},
                ),
            ]
        )
        db.flush()
        bundle_id = bundle.id
        db.commit()
    command.upgrade(config, "head")
    with Session(engine) as db:
        question = db.get(ApplicationQuestion, "q")
        draft = db.scalar(select(DraftVersion))
        outcome = db.scalar(select(SelectionOutcome))
        assert question is not None and question.state == "FINAL_LOCKED"
        assert draft is not None and draft.content == "본문"
        assert outcome is not None and outcome.result == "DOCUMENT_PASS"
        stored = db.scalar(select(SubmissionSnapshot))
        bundle = db.get(Artifact, bundle_id)
        assert stored is not None and bundle is not None
        assert stored.submitted_at is not None
        assert stored.content == snapshot == bundle.data
    engine.dispose()
