# ruff: noqa: F811 -- shared workflow and HTTP fixtures
from copy import deepcopy

import pytest
from career.artifacts import save
from career.db import Record
from career.models import Artifact, Evidence, Fact, Source
from career.project_boundaries import bind, catalog, context, document_issues, fingerprint
from career.references import register
from career.truth import add_evidence, register_source
from career.workflow import Workflow
from sqlalchemy import select
from test_api import client  # noqa: F401
from test_workflow import doc, flow, proof_payload, question  # noqa: F401

RULES = """# 10. Project guidance
## Synthetic evaluation
전체 시스템을 처음부터 개발했다고 쓰지 않는다.
정식 FAR/FRR 개선이나 실제 서비스 배포 성과로 표현하지 않는다.
Use only the evaluated component and its actual limits.
## Synthetic tracing
Agent 구축 경험으로 과장하지 않는다.
### Example
999% is not a personal result.
## Synthetic document experiment
실제 운영에서 검수시간/비용 감소를 측정한 것은 아니며 적용 가능성으로 표현한다.
# 12. Snapshot
Never import this snapshot as evidence.
"""


def apply(db, user, evidence, rule_index=0):
    rules = catalog(db, user)
    return bind(
        db,
        user,
        evidence.id,
        {"rule_id": rules[rule_index]["id"], "evidence_hash": fingerprint(evidence), "confirmed": True},
    )


def evidence_fixture(db, user="a", title="Synthetic evaluation", source=None):
    if source is None:
        source, _ = register_source(
            db, user, "synthetic-evaluation", "평가한 구성요소만 수정했습니다.", "RAW_RESULT"
        )
    return add_evidence(
        db,
        user,
        source.id,
        title,
        "평가한 구성요소만 수정했습니다.",
        {"ownership": {"implementation": "USER_MODIFIED_EXISTING_CODE"}},
        "VERIFIED",
    )


def document(text, evidence_id):
    return {
        "text": text,
        "claims": [
            {
                "text": text,
                "evidence_ids": [evidence_id],
                "type": "OWNERSHIP",
                "support": "SUPPORTED",
                "ownership_ok": True,
            }
        ],
    }


def test_catalog_is_current_user_source_backed_guidance_not_facts(db):
    register(db, "a", "cover", RULES)
    rows = catalog(db, "a")
    assert len(rows) == 3 and all(not row["fact_authority"] for row in rows)
    assert all("999%" not in row["text"] and row["start_line"] <= row["end_line"] for row in rows)
    assert catalog(db, "b") == []
    assert list(db.scalars(select(Fact))) == [] and list(db.scalars(select(Evidence))) == []


def test_matching_name_requires_explicit_selection_or_explicit_exclusion(db):
    register(db, "a", "cover", RULES)
    e = evidence_fixture(db)
    f = Workflow(db, "a")
    c = context(db, "a", e.id)
    assert c["suggested_rule_id"] and c["needs_review"] and c["binding"] is None
    with pytest.raises(ValueError, match="직접 확인"):
        f.selected([e.id])
    bind(db, "a", e.id, {"rule_id": "", "evidence_hash": c["evidence_hash"], "confirmed": True})
    assert not context(db, "a", e.id)["needs_review"]
    assert "project_boundary" not in f.selected([e.id])[0]["data"]
    assert e.body == "평가한 구성요소만 수정했습니다."


@pytest.mark.parametrize("confirmed", [False, "true", 1])
def test_binding_needs_current_hash_and_strict_confirmation(db, confirmed):
    register(db, "a", "cover", RULES)
    e = evidence_fixture(db)
    with pytest.raises(ValueError):
        bind(
            db,
            "a",
            e.id,
            {"rule_id": catalog(db, "a")[0]["id"], "evidence_hash": fingerprint(e), "confirmed": confirmed},
        )
    with pytest.raises(ValueError, match="대응"):
        bind(db, "a", e.id, {"rule_id": "", "evidence_hash": "0" * 64, "confirmed": True})


def test_binding_is_owned_idempotent_and_rejects_expression_or_invalid_source(db):
    register(db, "a", "cover", RULES)
    register(db, "b", "cover", RULES.replace("component", "other"))
    e = evidence_fixture(db)
    with pytest.raises(LookupError):
        context(db, "b", e.id)
    with pytest.raises(ValueError, match="활성 원문"):
        bind(
            db,
            "a",
            e.id,
            {"rule_id": catalog(db, "b")[0]["id"], "evidence_hash": fingerprint(e), "confirmed": True},
        )
    first = apply(db, "a", e)
    again = apply(db, "a", e)
    assert first["binding"] == again["binding"] and again["stale_artifacts"] == []
    assert len(list(db.scalars(select(Record).where(Record.kind == "ProjectBoundary")))) == 1
    e.kind = "EXPRESSION"
    with pytest.raises(ValueError, match="사실 근거"):
        apply(db, "a", e)
    e.kind = "EVIDENCE"
    source = db.get(Source, e.source_id)
    assert source is not None
    source.status = "DO_NOT_USE"
    with pytest.raises(ValueError, match="출처"):
        apply(db, "a", e)


def test_binding_changes_only_related_artifacts_preserves_frozen_and_other_user(db):
    register(db, "a", "cover", RULES)
    e = evidence_fixture(db)
    # Another experience shares the raw source but is not this rule binding.
    other = evidence_fixture(db, title="Separate component", source=db.get(Source, e.source_id))
    f = Workflow(db, "a")
    w = f.create("Synthetic", "Analyst", "Report")
    related, _ = save(
        db,
        "a",
        w.id,
        "EvidencePack",
        {"items": [{"evidence_id": e.id, "job_output_id": "Report", "classification": "ADJACENT"}]},
    )
    downstream, _ = save(db, "a", w.id, "Draft", document("synthetic", e.id), deps=[related.id])
    unrelated, _ = save(db, "a", w.id, "Unrelated", {"selected_evidence_ids": [other.id]})
    frozen = Artifact(
        user_id="a",
        workspace_id=w.id,
        kind="SubmissionBundle",
        status="LOCKED",
        version=1,
        data={"selected_evidence_ids": [e.id], "immutable": "synthetic"},
        source_ids=[e.source_id],
        depends_on=[downstream.id],
    )
    foreign = Artifact(
        user_id="b", workspace_id="other", kind="Draft", data={"selected_evidence_ids": [e.id]}
    )
    db.add_all([frozen, foreign])
    db.flush()
    snapshot = deepcopy(frozen.data)
    first = apply(db, "a", e)
    assert set(first["stale_artifacts"]) == {related.id, downstream.id}
    assert unrelated.status == "ACTIVE" and foreign.status == "ACTIVE"
    assert frozen.status == "LOCKED" and frozen.data == snapshot


def test_source_or_evidence_change_requires_rebinding_and_new_version(db):
    register(db, "a", "cover", RULES)
    e = evidence_fixture(db)
    apply(db, "a", e)
    e.body += " 변경된 판단입니다."
    assert context(db, "a", e.id)["needs_review"]
    with pytest.raises(ValueError, match="경험이 변경"):
        Workflow(db, "a").selected([e.id])
    assert apply(db, "a", e)["binding"]["version"] == 2
    register(db, "a", "cover", RULES.replace("actual limits", "verified limits"))
    with pytest.raises(ValueError, match="원문이 변경"):
        Workflow(db, "a").selected([e.id])
    assert apply(db, "a", e)["binding"]["version"] == 3


@pytest.mark.parametrize(
    "text,code",
    [
        ("전체 시스템을 처음부터 직접 개발했습니다.", "FULL_BUILD"),
        ("정식 FAR/FRR을 개선했습니다.", "FORMAL_RATE"),
        ("실제 서비스에 배포했습니다.", "DEPLOYMENT"),
        ("전체 시스템을 처음부터 개발했지만 배포하지 않았습니다.", "FULL_BUILD"),
    ],
)
def test_scoped_prohibition_flags_assertion_even_if_later_clause_is_negated(db, text, code):
    register(db, "a", "cover", RULES)
    e = evidence_fixture(db)
    apply(db, "a", e)
    selected = Workflow(db, "a").selected([e.id])
    issues = document_issues(document(text, e.id), selected)
    assert any(issue["code"] == "PROJECT_BOUNDARY_" + code and issue["priority"] == "P1" for issue in issues)


@pytest.mark.parametrize(
    "text",
    [
        "전체 시스템을 처음부터 개발하지 않았습니다.",
        "전체 시스템을 처음부터 개발한 것이 아닙니다.",
        "실제 서비스 배포를 계획했습니다.",
        "실제 서비스에 적용할 수 있다는 가능성을 평가했습니다.",
        "실제 서비스에 배포하고 싶습니다.",
        "실제 서비스에 배포하려고 준비했습니다.",
        "FAR/FRR 개선을 목표로 실험했습니다.",
        "검증 구성요소를 직접 개발했습니다.",
    ],
)
def test_actual_component_work_negation_and_future_scope_are_not_outcomes(db, text):
    register(db, "a", "cover", RULES)
    e = evidence_fixture(db)
    apply(db, "a", e)
    assert document_issues(document(text, e.id), Workflow(db, "a").selected([e.id])) == []


def test_agent_and_measured_saving_rules_apply_only_to_linked_claims(db):
    register(db, "a", "cover", RULES)
    e = evidence_fixture(db, title="Synthetic tracing")
    apply(db, "a", e, 1)
    selected = Workflow(db, "a").selected([e.id])
    assert document_issues(document("Agent 시스템을 직접 구축했습니다.", e.id), selected)
    assert not document_issues(document("에이전트 실패를 분석하며 기록 도구를 개발했습니다.", e.id), selected)
    assert not document_issues(document("Agent 시스템을 직접 구축했습니다.", "unrelated"), selected)
    saved = evidence_fixture(db, title="Synthetic document experiment")
    apply(db, "a", saved, 2)
    assert document_issues(
        document("실제 검수 시간을 단축했습니다.", saved.id), Workflow(db, "a").selected([saved.id])
    )
    assert not document_issues(
        document("검수 시간 단축을 목표로 실험했습니다.", saved.id), Workflow(db, "a").selected([saved.id])
    )
    assert not document_issues(
        document("검수 시간 단축의 가능성을 평가했습니다.", saved.id), Workflow(db, "a").selected([saved.id])
    )


def test_untrusted_evidence_data_cannot_forge_or_disable_binding(db):
    register(db, "a", "cover", RULES)
    e = evidence_fixture(db)
    e.data = {**e.data, "project_boundary": {"checks": [], "fact_authority": True}}
    apply(db, "a", e)
    row = Workflow(db, "a").selected([e.id])[0]
    assert not row["data"]["project_boundary"]["fact_authority"]
    assert row["data"]["project_boundary"]["checks"]
    assert not list(db.scalars(select(Fact)))


def test_manual_pass_cannot_override_claim_test_boundary_and_cover_resume_review(flow):
    f, w, e = flow
    register(f.db, "a", "cover", RULES)
    apply(f.db, "a", e)
    # Recompute artifacts explicitly after the new binding invalidates the old pack.
    f.map_evidence(
        w.id,
        {
            "items": [
                {
                    "evidence_id": e.id,
                    "job_output_id": "평가 보고서",
                    "classification": "DIRECT",
                    "evidence_strength": "STRONG",
                    "ownership_strength": "STRONG",
                    "rationale": "실험 설계",
                }
            ],
            "uncovered_outputs": [],
        },
    )
    f.strategy(
        w.id,
        {
            "positioning": "평가 연구원",
            "base_profession_identity": "연구원",
            "main_skill_message": "실험 검증",
            "assignment_statement": "평가 실험을 설계하고 결과를 확인합니다.",
        },
    )
    f.approve_strategy(w.id)
    q = question(f, w, e, "전체 시스템을 처음부터 직접 개발했습니다.", tested=False)
    brief = f.artifact(w.id, "QuestionBrief", q["id"])
    proof = f.test_claim(w.id, q["id"], proof_payload(brief.data, e), confirmed=True)
    assert proof.data["result"] == "NEEDS_REVISION"
    assert any(issue["code"] == "PROJECT_BOUNDARY_FULL_BUILD" for issue in proof.data["hard_issues"])
    with pytest.raises(ValueError, match="Evidence Test"):
        f.approve_question(w.id, q["id"])
    brief = f.question_brief(w.id, q["id"], {**brief.data, "primary_message": "평가 실험을 검증했습니다."})
    f.test_claim(w.id, q["id"], proof_payload(brief.data, e), confirmed=True)
    f.approve_question(w.id, q["id"])
    bad = document("전체 시스템을 처음부터 직접 개발했습니다.", e.id)
    for resume in (False, True):
        item = f.resume(w.id, bad) if resume else f.draft(w.id, q["id"], bad)
        review = f.review(w.id, "" if resume else q["id"], resume=resume, manual_verified=True)
        assert any(issue["code"] == "PROJECT_BOUNDARY_FULL_BUILD" for issue in review.data["issues"])
        # Even an accidentally clean stored review cannot bypass the current check.
        review.data = {**review.data, "issues": []}
        with pytest.raises(ValueError, match="프로젝트 표현 제한"):
            f.final_lock(w.id, "" if resume else q["id"], resume=resume)
        assert item.status == "ACTIVE"


def test_http_isolation_and_confirmation_schema(client):
    from career.api import app, database

    client.headers["Authorization"] = "Bearer alice-key"
    e = client.post(
        "/api/evidence",
        json={
            "title": "Synthetic evaluation",
            "source_title": "test",
            "body": "Component evaluation.",
            "confirmed": True,
        },
    ).json()
    generator = app.dependency_overrides[database]()
    session = next(generator)
    register(session, "alice", "cover", RULES)
    session.commit()
    generator.close()
    path = f"/api/evidence/{e['id']}/project-boundary"
    current = client.get(path).json()
    body = {
        "rule_id": current["rules"][0]["id"],
        "evidence_hash": current["evidence_hash"],
        "confirmed": True,
    }
    assert client.post(path, json={**body, "confirmed": "true"}).status_code == 422
    assert client.post(path, json={**body, "evidence_hash": "0" * 64}).status_code == 409
    assert client.post(path, json=body).status_code == 200
    client.headers["Authorization"] = "Bearer bob-key"
    assert client.get(path).status_code == 404
    assert client.post(path, json=body).status_code == 404


def test_cover_and_resume_writers_receive_same_bound_guidance_and_source_dependency(flow, monkeypatch):
    f, w, e = flow
    reference = register(f.db, "a", "cover", RULES)
    apply(f.db, "a", e)
    f.map_evidence(
        w.id,
        {
            "items": [
                {
                    "evidence_id": e.id,
                    "job_output_id": "평가 보고서",
                    "classification": "DIRECT",
                    "evidence_strength": "STRONG",
                    "ownership_strength": "STRONG",
                    "rationale": "실험 설계",
                }
            ],
            "uncovered_outputs": [],
        },
    )
    f.strategy(
        w.id,
        {
            "positioning": "평가 연구원",
            "base_profession_identity": "연구원",
            "main_skill_message": "실험 검증",
            "assignment_statement": "평가 실험을 설계하고 결과를 확인합니다.",
        },
    )
    f.approve_strategy(w.id)
    q = question(f, w, e)
    f.approve_question(w.id, q["id"])
    fixtures = {
        "writer": doc(e),
        "resume_writer": {
            "sections": [
                {
                    "kind": "PROJECT",
                    "title": "Synthetic",
                    "bullets": [{"text": e.body, "evidence_ids": [e.id], "claims": doc(e)["claims"]}],
                }
            ]
        },
    }
    seen = {}

    def generate(stage, inputs, schema):
        seen[stage] = deepcopy(inputs)
        return schema.model_validate(fixtures[stage]).model_dump()

    monkeypatch.setattr(f, "ai", generate)
    cover = f.draft(w.id, q["id"])
    resume = f.resume(w.id)
    for stage in ("writer", "resume_writer"):
        guidance = seen[stage]["evidence"][0]["data"]["project_boundary"]
        assert guidance["text"] == catalog(f.db, "a")[0]["text"]
        assert guidance["fact_authority"] is False
    assert reference.data["source_id"] in cover.source_ids
    assert reference.data["source_id"] in resume.source_ids
    from career.references import activate

    activate(f.db, "a", reference.id, False)
    assert cover.status == "STALE" and resume.status == "STALE"
    assert not list(f.db.scalars(select(Fact)))
