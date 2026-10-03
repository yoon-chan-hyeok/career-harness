import pytest
from career.activity import execution_id, run_operation, snapshot
from career.db import now
from career.models import Artifact, ExecutionRun, PromptRun
from career.providers import ProviderUnavailable
from career.runtime_trace import emit_trace, input_hash
from career.workflow import Workflow
from sqlalchemy import select
from sqlalchemy.orm import Session


def workspace(db):
    result = Workflow(db, "owner").create("Fixture", "Research", "Produce a report")
    db.commit()
    return result


def test_run_is_visible_while_working_and_one_request_per_workspace(db):
    ws = workspace(db)

    def operation():
        with Session(db.bind) as observer:
            visible = snapshot(observer, "owner", ws.id)
            assert visible["active_run"]["status"] == "RUNNING"
            assert visible["stages"][0]["status"] == "RUNNING"
            with pytest.raises(ValueError, match="진행"):
                run_operation(observer, "owner", ws.id, "analyze", lambda: None)
        return {"data": {"response": {"status": "OK"}}}

    run_operation(db, "owner", ws.id, "research", operation)
    db.commit()
    result = snapshot(db, "owner", ws.id)
    assert result["active_run"] is None
    assert result["runs"][0]["status"] == "COMPLETED"
    assert result["runs"][0]["elapsed_ms"] >= 0
    with pytest.raises(LookupError):
        snapshot(db, "other", ws.id)


def test_failed_operation_rolls_back_document_but_preserves_safe_trace(db):
    ws = workspace(db)

    def operation():
        db.add(Artifact(user_id="owner", workspace_id=ws.id, kind="Draft", data={"text": "temporary"}))
        emit_trace(
            "writer",
            "Fixture",
            {
                "status": "FAILED",
                "input_hash": input_hash("private fixture"),
                "error_code": "PROVIDER_UNAVAILABLE",
                "prompt": "private fixture",
            },
        )
        db.flush()
        raise ProviderUnavailable("provider is unavailable")

    with pytest.raises(ProviderUnavailable):
        run_operation(db, "owner", ws.id, "generate", operation)
    assert list(db.scalars(select(Artifact))) == []
    trace = db.scalar(select(PromptRun))
    assert trace is not None and trace.data["status"] == "FAILED"
    assert "private fixture" not in str(trace.data)
    assert snapshot(db, "owner", ws.id)["runs"][0]["error_code"] == "PROVIDER_UNAVAILABLE"
    assert execution_id.get() is None


def test_recovered_execution_is_fenced_from_committing_late_results(db, monkeypatch):
    from datetime import timedelta

    ws = workspace(db)
    monkeypatch.setenv("EXECUTION_TIMEOUT_SECONDS", "1")

    def operation():
        with Session(db.bind) as observer:
            run = observer.get(ExecutionRun, execution_id.get())
            assert run is not None
            run.created_at = now() - timedelta(seconds=5)
            observer.commit()
            assert snapshot(observer, "owner", ws.id)["runs"][0]["error_code"] == "EXECUTION_INTERRUPTED"
            observer.commit()
        db.add(Artifact(user_id="owner", workspace_id=ws.id, kind="Draft", data={"text": "late result"}))
        return {}

    with pytest.raises(ValueError, match="중단"):
        run_operation(db, "owner", ws.id, "generate", operation)
    assert list(db.scalars(select(Artifact))) == []
    assert snapshot(db, "owner", ws.id)["runs"][0]["error_code"] == "EXECUTION_INTERRUPTED"
