# ruff: noqa: F811 -- shared isolated API fixture
import json
from copy import deepcopy
from uuid import uuid4

import pytest
from career import admin, provider_config
from career.activity import snapshot
from career.api import app, database
from career.artifacts import latest
from career.experience_options import ExperienceChoiceRequest, active_selection, choose, options
from career.models import Artifact, ExecutionRun, PromptRun, Workspace
from career.truth import add_evidence, register_source
from career.workflow import Workflow
from test_api import client  # noqa: F401
from test_workflow import doc


def scene(db, user="alice", count=4):
    service = Workflow(db, user)
    workspace = service.create("합성 회사", "평가 연구원", "평가 보고서 작성")
    service.analyze(workspace.id, {"actual_outputs": ["평가 보고서"], "base_profession": "연구원"})
    evidence = []
    for number in range(count):
        body = f"실험 {number}의 조건을 직접 설계하고 평가 보고서를 작성했습니다."
        source, _ = register_source(db, user, f"synthetic-{number}", body, "RAW_RESULT")
        evidence.append(add_evidence(db, user, source.id, f"합성 경험 {number}", body,
                                     {"ownership": {"implementation": "USER"}}, "VERIFIED"))
    service.map_evidence(workspace.id, {"items": [{"evidence_id": item.id, "job_output_id": "평가 보고서",
                                                  "classification": "DIRECT", "evidence_strength": "STRONG",
                                                  "ownership_strength": "STRONG", "rationale": "확인된 평가 보고서",
                                                  "concrete_output": "평가 보고서"} for item in evidence],
                                        "uncovered_outputs": []})
    service.strategy(workspace.id, {"positioning": "연구원", "base_profession_identity": "연구원",
                                    "main_skill_message": "실험 검증", "assignment_statement": "평가 보고서 작성"})
    return service, workspace, evidence


def choice(value, evidence_id):
    return ExperienceChoiceRequest(slot=value["slot"], evidence_id=evidence_id,
                                   base_artifact_id=value["base_artifact_id"],
                                   base_artifact_version=value["base_artifact_version"],
                                   options_revision=value["options_revision"])


def brief(qid, evidence_id):
    return {"question_id": qid, "question_type": "JOB_COMPETENCY", "evaluation_intent": "검증",
            "primary_message": "실험 조건을 직접 설계했습니다.", "evidence_ids": [evidence_id]}


def test_options_are_bounded_distinct_verified_and_owned(db):
    service, workspace, evidence = scene(db, count=6)
    evidence[1].title = evidence[0].title
    evidence[2].status = "UNVERIFIED"
    evidence[3].status = "DO_NOT_USE"
    evidence[4].data = {"ownership": {"implementation": "UNKNOWN"}}
    evidence[5].kind = "EXPRESSION"
    result = options(service, workspace.id)
    assert len(result["options"]) == 1
    assert result["options"][0]["evidence_id"] in {evidence[0].id, evidence[1].id}
    assert result["options"][0]["source_ids"]
    assert result["options"][0]["recommended"]
    assert "현재 근거 매핑" in result["options"][0]["recommendation_reason"]
    assert not list(db.query(Artifact).filter_by(kind="ExperienceSelection"))
    with pytest.raises(LookupError):
        options(Workflow(db, "bob"), workspace.id)
    # A corrupted cross-user relation fails closed instead of returning a title.
    source, _ = register_source(db, "bob", "bob-private", "private-body", "RAW_RESULT")
    foreign = add_evidence(db, "bob", source.id, "private-title", "private-body",
                           {"ownership": {"implementation": "USER"}}, "VERIFIED")
    pack = service.artifact(workspace.id, "EvidencePack")
    pack.data = {**pack.data, "items": [*pack.data["items"], {**pack.data["items"][0], "evidence_id": foreign.id}]}
    with pytest.raises(LookupError):
        options(service, workspace.id)


def test_question_choice_stales_old_writing_then_drives_approved_writer_context(db, monkeypatch):
    service, workspace, evidence = scene(db)
    service.approve_strategy(workspace.id)
    q = service.add_question(workspace.id, "직무 역량을 설명하세요.", 1000)
    service.question_brief(workspace.id, q["id"], brief(q["id"], evidence[0].id))
    service.approve_question(workspace.id, q["id"])
    original = service.draft(workspace.id, q["id"], doc(evidence[0]))
    candidates = options(service, workspace.id, q["id"])
    chosen_id = next(item["evidence_id"] for item in candidates["options"] if item["evidence_id"] != evidence[0].id)
    chosen = next(item for item in evidence if item.id == chosen_id)
    result = choose(service, workspace.id, choice(candidates, chosen_id))
    assert original.id in result["stale_artifacts"] and original.status == "STALE"
    assert result["requires_approval"] and result["selection"]["data"]["approval_granted"] is False
    with pytest.raises(ValueError):
        service.approve_question(workspace.id, q["id"])
    with pytest.raises(ValueError, match="선택"):
        service.question_brief(workspace.id, q["id"], brief(q["id"], evidence[0].id))
    new_brief = service.question_brief(workspace.id, q["id"], brief(q["id"], chosen_id))
    assert result["selection"]["id"] in new_brief.depends_on
    with pytest.raises(ValueError, match="승인"):
        service.draft(workspace.id, q["id"], doc(chosen))
    service.approve_question(workspace.id, q["id"])
    captured = {}

    def fake_ai(stage, context, schema):
        captured.update({"stage": stage, "context": context})
        return doc(chosen)

    monkeypatch.setattr(service, "ai", fake_ai)
    generated = service.draft(workspace.id, q["id"])
    assert captured["stage"] == "writer"
    assert [item["id"] for item in captured["context"]["evidence"]] == [chosen_id]
    assert captured["context"]["brief"]["experience_selection_artifact_id"] == result["selection"]["id"]
    assert generated.data["selected_evidence_ids"] == [chosen_id]
    # Persisted selection can be loaded by a new service/session.
    db.commit()
    persisted = active_selection(Workflow(db, "alice"), workspace.id, q["id"])
    assert persisted is not None and persisted.id == result["selection"]["id"]


def test_choice_rejects_old_versions_changed_facts_unknown_ownership_and_frozen_state(db):
    service, workspace, evidence = scene(db)
    candidates = options(service, workspace.id)
    request = choice(candidates, candidates["options"][0]["evidence_id"])
    evidence[0].body += " 현재 내용 변경"
    with pytest.raises(ValueError, match="버전"):
        choose(service, workspace.id, request)
    candidates = options(service, workspace.id)
    pack = service.artifact(workspace.id, "EvidencePack")
    mapped = {"items": [{key: value for key, value in item.items() if key in {
        "evidence_id", "job_output_id", "classification", "evidence_strength", "ownership_strength", "rationale",
        "skill_focus", "skill_name", "concrete_output", "understandable_hook"}} for item in pack.data["items"]],
        "uncovered_outputs": []}
    service.map_evidence(workspace.id, mapped)
    with pytest.raises(ValueError, match="버전"):
        choose(service, workspace.id, choice(candidates, candidates["options"][0]["evidence_id"]))
    candidates = options(service, workspace.id)
    chosen_id = candidates["options"][0]["evidence_id"]
    selection = choose(service, workspace.id, choice(candidates, chosen_id))
    item = next(item for item in evidence if item.id == chosen_id)
    item.data = {"ownership": {"implementation": "UNKNOWN"}}
    with pytest.raises(ValueError, match="수행 범위"):
        active_selection(service, workspace.id, "strategy")
    assert options(service, workspace.id)["selection_status"] == "STALE"
    item.data = {"ownership": {"implementation": "USER"}}
    assert selection["selection"]["data"]["option"]["evidence_id"] == chosen_id
    for state in ("SUBMISSION_FROZEN", "SUBMITTED", "CLOSED"):
        workspace.state = state
        with pytest.raises(ValueError, match="보관본"):
            choose(service, workspace.id, choice(options(service, workspace.id), chosen_id))


def test_strategy_choice_requires_approval_even_fast_and_resume_really_prioritizes_choice(db):
    service, workspace, evidence = scene(db)
    workspace.mode = "FAST"
    candidates = options(service, workspace.id)
    chosen_id = candidates["options"][-1]["evidence_id"]
    selection = choose(service, workspace.id, choice(candidates, chosen_id))
    previous_strategy = latest(db, "alice", workspace.id, "ApplicationBrief")
    assert previous_strategy is not None
    strategy_data = deepcopy(previous_strategy.data)
    strategy = service.strategy(workspace.id, strategy_data)
    assert strategy.status == "ACTIVE" and workspace.state == "WAITING_STRATEGY_APPROVAL"
    assert strategy.data["selected_experience_id"] == chosen_id
    assert selection["selection"]["id"] in strategy.depends_on
    service.approve_strategy(workspace.id)
    chosen = next(item for item in evidence if item.id == chosen_id)
    resume = service.resume(workspace.id, doc(chosen))
    assert resume.data["selected_evidence_ids"][0] == chosen_id
    resume_brief = service.artifact(workspace.id, "ResumeBrief")
    assert resume_brief.data["project_order"][0] == chosen.title
    assert resume_brief.data["experience_selection_artifact_id"] == selection["selection"]["id"]
    candidate = options(service, workspace.id, "resume")
    assert candidate["selected_evidence_id"] == chosen_id
    assert candidate["inherited_from"] == "strategy"
    other = next(item for item in candidate["options"] if item["evidence_id"] != chosen_id)
    result = choose(service, workspace.id, choice(candidate, other["evidence_id"]))
    assert resume.status == "STALE" and result["selection"]["data"]["option"] == other


def test_options_show_actual_other_question_usage_without_banning_reuse(db):
    service, workspace, evidence = scene(db, count=1)
    service.approve_strategy(workspace.id)
    one = service.add_question(workspace.id, "역량", 500)
    two = service.add_question(workspace.id, "협업", 500)
    service.question_brief(workspace.id, one["id"], brief(one["id"], evidence[0].id))
    candidate = options(service, workspace.id, two["id"])
    assert candidate["options"][0]["used_in_slots"] == [one["id"]]
    assert candidate["options"][0]["usage_count"] == 1
    assert choose(service, workspace.id, choice(candidate, evidence[0].id))["selection"]


def test_experience_options_http_auth_isolation_and_optimistic_conflict(client):
    generator = app.dependency_overrides[database]()
    db = next(generator)
    _, workspace, _ = scene(db)
    workspace_id = workspace.id
    db.commit()
    generator.close()
    path = f"/api/applications/{workspace_id}/experience-options"
    assert client.get(path).status_code == 401
    client.headers["Authorization"] = "Bearer bob-key"
    assert client.get(path).status_code == 404
    client.headers["Authorization"] = "Bearer alice-key"
    candidates = client.get(path).json()
    body = choice(candidates, candidates["options"][0]["evidence_id"]).model_dump()
    assert client.post(path + "/select", json={**body, "evidence_id": str(uuid4())}).status_code == 409
    response = client.post(path + "/select", json=body)
    assert response.status_code == 200 and response.json()["selection"]["kind"] == "ExperienceSelection"
    client.headers["Authorization"] = "Bearer bob-key"
    assert client.post(path + "/select", json=body).status_code == 404


def test_admin_is_server_authorized_self_scoped_and_redacts_raw_content(client, monkeypatch):
    assert client.get("/api/admin/status").status_code == 401
    client.headers["Authorization"] = "Bearer alice-key"
    assert client.get("/api/admin/access").json() == {"is_admin": False}
    assert client.get("/api/admin/status").status_code == 403
    provider_config.LOCAL_SETTINGS_PATH.write_text(json.dumps({"user": "alice"}), encoding="utf-8")
    assert client.get("/api/admin/access").json()["is_admin"]
    generator = app.dependency_overrides[database]()
    db = next(generator)
    alice = Workspace(user_id="alice", company="secret-alice", role="role", jd_raw="secret-original")
    bob = Workspace(user_id="bob", company="secret-bob", role="role", jd_raw="secret-original-bob")
    db.add_all([alice, bob])
    db.flush()
    db.add_all([ExecutionRun(user_id="alice", workspace_id=alice.id, action="resume", label="secret-label",
                             status="FAILED", error_code="SECRET_PRIVATE_EXCEPTION", message="raw-secret",
                             data={"prompt": "secret-prompt"}),
                ExecutionRun(user_id="bob", workspace_id=bob.id, action="research", label="bob-secret",
                             status="FAILED", error_code="EXECUTION_FAILED", data={})])
    db.commit()
    generator.close()
    monkeypatch.setenv("CAREER_SOURCE_REPOSITORY_URL", "https://user:secret@github.com/owner/repo?token=secret")
    response = client.get("/api/admin/status")
    value = response.json()
    assert response.status_code == 200 and value["scope"] == "CURRENT_ACCOUNT"
    assert value["counts"]["applications"] == 1 and value["counts"]["failed_executions"] == 1
    assert len(value["recent_executions"]) == 1 and value["recent_executions"][0]["error_code"] is None
    assert value["recent_executions"][0]["started_at"].endswith("+00:00")
    assert value["source_repository_url"] is None
    for private in ("secret-bob", "secret-alice", "secret-original", "raw-secret", "secret-prompt", "PRIVATE_EXCEPTION"):
        assert private not in response.text
    client.headers["Authorization"] = "Bearer bob-key"
    assert client.get("/api/admin/status").status_code == 403


def test_production_admin_fail_closed_and_repository_url_validation(monkeypatch):
    administrator = str(uuid4())
    monkeypatch.setenv("CAREER_ENV", "production")
    monkeypatch.delenv("CAREER_ADMIN_USER_IDS", raising=False)
    monkeypatch.setenv("CAREER_ALLOWED_USER_IDS", administrator)
    assert not admin.is_admin(administrator)
    monkeypatch.setenv("CAREER_ADMIN_USER_IDS", administrator)
    assert admin.is_admin(administrator) and not admin.is_admin(str(uuid4()))
    monkeypatch.setenv("CAREER_ADMIN_USER_IDS", administrator + ",invalid-id")
    assert not admin.is_admin(administrator)
    for url in ("javascript:alert(1)", "https://github.com.evil/owner/repo", "https://token@github.com/owner/repo",
                "https://github.com/owner/repo?token=private", "https://github.com/owner/repo/tree/private",
                "https://[malformed-private-host/owner/repo"):
        monkeypatch.setenv("CAREER_SOURCE_REPOSITORY_URL", url)
        assert admin.source_repository_url() is None
    monkeypatch.setenv("CAREER_SOURCE_REPOSITORY_URL", "https://github.com/owner/repo/")
    assert admin.source_repository_url() == "https://github.com/owner/repo"


def test_pixel_roles_derive_only_from_own_actual_records(db):
    service, workspace, _ = scene(db)
    no_records = snapshot(db, "alice", workspace.id)
    assert len(no_records["roles"]) == 6
    writing = next(role for role in no_records["roles"] if role["key"] == "writing")
    assert writing["basis"] == "NO_ACTIVITY" and writing["trace_id"] is None
    trace = PromptRun(user_id="alice", stage="writer", provider="HuggingFace",
                      data={"workspace_id": workspace.id, "status": "COMPLETED", "model": "synthetic/model",
                            "prompt": "never-surface-private", "output": "never-surface-output"})
    foreign = PromptRun(user_id="bob", stage="writer", provider="HuggingFace",
                        data={"workspace_id": workspace.id, "model": "bob-private-model"})
    db.add_all([trace, foreign])
    db.flush()
    result = snapshot(db, "alice", workspace.id)
    writing = next(role for role in result["roles"] if role["key"] == "writing")
    assert writing["basis"] == "PROMPT_TRACE" and writing["trace_id"] == trace.id
    assert writing["model"] == "synthetic/model" and writing["status"] == "NOT_STARTED"
    assert all(value not in str(result) for value in ("never-surface-private", "never-surface-output", "bob-private"))
