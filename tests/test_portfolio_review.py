# ruff: noqa: F811 -- shared HTTP fixture
from copy import deepcopy

import pytest
from career.artifacts import latest
from career.domain import save_entity
from career.models import Artifact
from career.portfolio import approve, plan
from career.portfolio_review import current, policy
from career.references import register
from career.truth import add_evidence, register_source
from career.workflow import Workflow
from final_review_fixture import confirm_final
from sqlalchemy import select
from test_api import client  # noqa: F401
from test_workflow import proof_payload

REPETITION = "# 5. Portfolio\n## 5-4. 소재 중복 규칙\n금지: 같은 Fact, 같은 숫자, 같은 결론, 같은 메시지의 반복.\n같은 경험의 다른 역할은 허용한다."


def prepared(db, user="a", two_questions=False, write_second=True):
    source, _ = register_source(
        db, user, "synthetic-reports", "검증 보고서 3개와 대시보드 4개를 작성했습니다.", "RAW_RESULT"
    )
    e = add_evidence(
        db,
        user,
        source.id,
        "Synthetic evaluation",
        "검증 보고서 3개와 대시보드 4개를 작성했습니다.",
        {"ownership": {"implementation": "USER"}},
        "VERIFIED",
    )
    metric = save_entity(
        db,
        user,
        "Metric",
        {
            "source_id": source.id,
            "evidence_id": e.id,
            "name": "검증 보고서 수",
            "value": "3",
            "unit": "개",
            "dataset": "synthetic",
            "subset": "reports",
            "experiment_version": "fixture",
            "baseline": None,
            "denominator": None,
            "valid_for_claims": ["검증 보고서"],
            "invalid_for_claims": [],
            "status": "VERIFIED",
        },
    )
    f = Workflow(db, user)
    w = f.create("Synthetic", "평가 연구원", "평가 보고서를 작성합니다.")
    f.analyze(w.id, {"actual_outputs": ["평가 보고서"], "base_profession": "평가 연구원"})
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
                    "rationale": "실험 수행",
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
            "assignment_statement": "평가 실험과 결과 보고서를 작성할 수 있습니다.",
        },
    )
    f.approve_strategy(w.id)
    qs = [f.add_question(w.id, "실험 판단을 설명하세요.", 1000)]
    if two_questions:
        qs.append(f.add_question(w.id, "팀의 협업 기준을 설명하세요.", 1000))
        plan(
            f,
            w.id,
            {
                "items": [
                    {
                        "question_id": q["id"],
                        "identity_role": role,
                        "evaluation_intent": role,
                        "primary_message_candidates": [role],
                        "evidence_candidate_ids": [e.id],
                        "avoided_repetition": [],
                    }
                    for q, role in zip(qs, ["실험 설계", "협업 조율"], strict=True)
                ]
            },
        )
        approve(f, w.id)
    for index, q in enumerate(qs):
        if index and not write_second:
            continue
        brief = f.question_brief(
            w.id,
            q["id"],
            {
                "question_id": q["id"],
                "question_type": "JOB_COMPETENCY",
                "evaluation_intent": "검증",
                "primary_message": ["실험 설계", "협업 조율"][index],
                "evidence_ids": [e.id],
            },
        )
        f.test_claim(w.id, q["id"], proof_payload(brief.data, e), confirmed=True)
        f.approve_question(w.id, q["id"])
        f.draft(w.id, q["id"], content(e, metric.id, "3"))
        f.review(w.id, q["id"], manual_verified=True)
        f.final_lock(w.id, q["id"])
    return f, w, e, metric, qs


def content(e, metric_id, value):
    text = f"검증 보고서 {value}개를 작성하고 결과를 확인했습니다."
    return {
        "text": text,
        "claims": [
            {
                "text": text,
                "type": "METRIC",
                "evidence_ids": [e.id],
                "metric_ids": [metric_id],
                "support": "SUPPORTED",
                "ownership_ok": True,
            }
        ],
    }


def test_current_whole_review_blocks_freeze_and_edited_resume_requires_new_review(db):
    f, w, e, m, qs = prepared(db)
    f.resume(w.id, content(e, m.id, "4"))
    f.review(w.id, resume=True, manual_verified=True)
    f.final_lock(w.id, resume=True)
    confirm_final(f, w.id)
    result = f.command(w.id, "ㄱㄱ", qs[0]["id"])
    whole = f.artifact(w.id, "PortfolioReview")
    assert whole.id in result["patched_artifacts"] and whole.data["result"] == "NEEDS_REVISION"
    assert any(i["code"] == "CROSS_DOCUMENT_METRIC_VALUE" for i in whole.data["issues"])
    db.commit()
    with pytest.raises(ValueError, match="전체 문서 검수"):
        f.command(w.id, "ㄱㄱ", qs[0]["id"])
    with pytest.raises(ValueError, match="문서 간 검수"):
        f.ready(w.id)
    w.state = "READY_TO_FREEZE"
    with pytest.raises(ValueError):
        f.freeze(w.id)
    assert latest(db, "a", w.id, "SubmissionBundle", required=False) is None
    f.resume(w.id, content(e, m.id, "3"))
    f.review(w.id, resume=True, manual_verified=True)
    f.final_lock(w.id, resume=True)
    assert current(f, w.id) is None and whole.status == "STALE"
    new = f.review_portfolio(w.id, manual_verified=True)
    assert new.data["result"] == "PASSED" and new.version == 2
    confirm_final(f, w.id)
    f.ready(w.id)
    bundle = f.freeze(w.id)
    snapshot = deepcopy(bundle.data)
    assert bundle.status == "LOCKED"
    f.db.refresh(bundle)
    assert bundle.data == snapshot


def test_strict_source_rule_blocks_same_fact_but_does_not_apply_other_user_policy(db):
    f, w, _, _, _ = prepared(db, two_questions=True)
    register(db, "other", "cover", REPETITION)
    assert not policy(f)["strict_repetition"]
    warning = f.review_portfolio(w.id, manual_verified=True)
    assert all(i["priority"] == "P2" for i in warning.data["issues"])
    register(db, "a", "cover", REPETITION)
    assert policy(f)["strict_repetition"]
    assert current(f, w.id) is None
    blocked = f.review_portfolio(w.id, manual_verified=True)
    assert blocked.data["result"] == "NEEDS_REVISION"
    assert any(i["code"] == "REPEATED_FACT" and i["priority"] == "P1" for i in blocked.data["issues"])
    assert blocked.source_ids and blocked.data["repetition_policy"]["sources"]


def test_evidence_change_invalidates_cached_review_even_without_document_version_change(db):
    from career.application_packet import packet_status

    f, w, e, _, _ = prepared(db)
    review = f.review_portfolio(w.id, manual_verified=True)
    cached = current(f, w.id)
    assert cached is not None and cached.id == review.id
    assert next(c for c in packet_status(db, "a", w.id)["checklist"] if c["code"] == "portfolio")["complete"]
    e.data = {**e.data, "ownership": {"implementation": "USER_AI_ASSISTED"}}
    assert current(f, w.id) is None
    assert not next(c for c in packet_status(db, "a", w.id)["checklist"] if c["code"] == "portfolio")["complete"]


def test_incomplete_review_reports_missing_documents_without_marking_ready(db):
    from career.application_packet import packet_status

    f, w, _, _, _ = prepared(db, two_questions=True, write_second=False)
    review = f.review_portfolio(w.id, manual_verified=True)
    assert not review.data["complete"] and w.state != "READY_TO_FREEZE"
    assert any(i["code"] == "PORTFOLIO_INCOMPLETE" for i in review.data["issues"])
    assert not next(c for c in packet_status(db, "a", w.id)["checklist"] if c["code"] == "portfolio")["complete"]


def test_api_persists_blocked_review_and_maintains_user_isolation(client):
    from career.api import app, database

    generator = app.dependency_overrides[database]()
    db = next(generator)
    f, w, e, m, _ = prepared(db, "alice")
    f.resume(w.id, content(e, m.id, "4"))
    f.review(w.id, resume=True, manual_verified=True)
    f.final_lock(w.id, resume=True)
    ident = w.id
    db.commit()
    generator.close()
    client.headers["Authorization"] = "Bearer alice-key"
    result = client.post(
        f"/api/applications/{ident}/actions/portfolio-review", json={"manual_verified": True}
    )
    assert result.status_code == 200 and result.json()["data"]["result"] == "NEEDS_REVISION"
    saved = client.get(f"/api/applications/{ident}").json()
    assert any(a["id"] == result.json()["id"] for a in saved["artifacts"])
    client.headers["Authorization"] = "Bearer bob-key"
    assert (
        client.post(
            f"/api/applications/{ident}/actions/portfolio-review", json={"manual_verified": True}
        ).status_code
        == 404
    )


def test_conversation_explicit_review_works_without_ai_and_keeps_document_locks(db):
    from career.conversation import ChatRequest, converse

    f, w, _, _, _ = prepared(db)
    before = {a.id: a.status for a in db.scalars(select(Artifact).where(Artifact.kind == "Draft"))}
    response = converse(f, w.id, ChatRequest(text="전체 문서 검수", client_id="synthetic-review-123"))
    assert response["data"]["response"]["artifact_ids"]
    assert f.artifact(w.id, "PortfolioReview").data["mode"] == "DETERMINISTIC"
    assert all(db.get(Artifact, ident).status == state for ident, state in before.items())


def test_semantic_review_receives_current_evidence_and_cannot_override_deterministic_conflict(db):
    f, w, e, m, _ = prepared(db)
    f.resume(w.id, content(e, m.id, "4"))
    seen = []

    class Reviewer:
        last_trace = {"model": "synthetic-review-only"}

        def structured(self, stage, context, schema):
            assert stage == "cross_document_consistency"
            seen.append(context)
            return schema.model_validate({"issues": [], "followups": ["지표의 기준을 다시 확인해 주세요."]})

    f.provider = Reviewer()
    review = f.review_portfolio(w.id)
    assert review.data["result"] == "NEEDS_REVISION"
    assert any(issue["code"] == "PORTFOLIO_FOLLOWUP" for issue in review.data["issues"])
    assert seen[0]["evidence"][0]["data"]["metric_ledger"][0]["id"] == m.id
    assert "canonical_profile" in seen[0] and "repetition_policy" in seen[0]
