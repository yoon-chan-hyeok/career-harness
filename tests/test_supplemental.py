# ruff: noqa: F811 -- imported pytest fixture is intentionally named by test arguments
import json
from copy import deepcopy

import pytest
from career.artifacts import latest
from career.assessment import assess, decide, rankings, validate_opportunity
from career.conversation import ChatRequest, converse
from career.db import Record
from career.entities import OwnershipRecord
from career.extraction import apply, propose
from career.human_review import propose_patch, resolve
from career.models import Evidence, Fact
from career.providers import FakeLLMProvider
from career.references import CATALOG, activate, compile_pack, listing, register
from career.resume_master import confirm_file_qa, master_context, save_master
from career.truth import add_fact, canonical, import_corpus, register_source, resolve_fact_conflict
from sqlalchemy import select
from test_workflow import doc, finish, flow, question  # noqa: F401


def install_refs(db, user="a"):
    return {
        key: register(db, user, key, "# fixture reference\nExample 999% must never become a fact.")
        for key in CATALOG
    }


def test_selective_packs_keep_domains_and_examples_separate(db):
    install_refs(db)
    assert {r["key"] for r in compile_pack(db, "a", "resume_writer")["references"]} == {
        "registry",
        "integrity",
        "resume",
    }
    assert {r["key"] for r in compile_pack(db, "a", "opportunity")["references"]} == {
        "registry",
        "integrity",
        "opportunity",
    }
    assert {r["key"] for r in compile_pack(db, "a", "writer")["references"]} == {
        "registry",
        "integrity",
        "cover",
        "expression",
    }
    assert {r["key"] for r in compile_pack(db, "a", "recruiter", "RESUME")["references"]} == {
        "registry",
        "integrity",
        "resume",
    }
    assert compile_pack(db, "b", "writer")["references"] == []
    assert "999%" not in json.dumps(compile_pack(db, "a", "writer"))
    assert not list(db.scalars(select(Evidence)))
    assert not list(db.scalars(select(Fact)))
    with pytest.raises(ValueError):
        add_fact(db, "a", listing(db, "a")[0]["source_id"], "metric", "invented", {"value": 999})


def test_importer_skips_supplemental_even_when_scanning_private_root(db, tmp_path):
    folder = tmp_path / "supplemental"
    folder.mkdir()
    (folder / "example.md").write_text("I deployed everything: 999%", encoding="utf-8")
    assert import_corpus(db, "a", tmp_path)["sources_added"] == 0
    assert not list(db.scalars(select(Evidence)))


def test_reference_change_stales_related_work_and_preserves_snapshot(flow):
    f, w, e = flow
    refs = install_refs(f.db)
    # Regenerate only the document under the activated cover pack.
    q = finish(f, w, e)
    from final_review_fixture import confirm_final

    confirm_final(f, w.id)
    f.ready(w.id)
    bundle = f.freeze(w.id)
    frozen = deepcopy(bundle.data)
    draft = f.artifact(w.id, "Draft", q["id"])
    assert refs["cover"].data["source_id"] in draft.source_ids
    activate(f.db, f.user, refs["cover"].id, False)
    assert draft.status == "STALE"
    assert bundle.status == "LOCKED" and bundle.data == frozen
    assert not any(r["key"] == "cover" for r in compile_pack(f.db, f.user, "writer")["references"])
    with pytest.raises(LookupError):
        activate(f.db, "someone-else", refs["cover"].id, True)


def test_ai_trace_records_versions_and_resume_pack(flow):
    f, _, _ = flow
    install_refs(f.db)
    capture = {}

    class Provider:
        last_trace = {"model": "fixture"}

        def structured(self, stage, context, schema):
            capture.update(context)
            return schema.model_validate({"issues": [], "followups": []})

    from career.models import PromptRun
    from career.schemas import Review

    f.provider = Provider()
    f.ai("recruiter", {"document_domain": "RESUME"}, Review)
    assert capture["supplemental_guidance"]["pack"] == "resume"
    trace = f.db.scalar(select(PromptRun))
    assert trace.data["reference_versions"] and trace.data["input_hash_only"]
    assert '"content":' not in json.dumps(trace.data)


def test_deadline_requires_aware_time_and_consistent_timezone():
    validate_opportunity(
        {
            "actual_outputs": ["report"],
            "deadline_at": "2026-10-30T18:00:00+09:00",
            "deadline_timezone": "Asia/Seoul",
        },
        set(),
    )
    for deadline, tz in [
        ("2026-10-30", "Asia/Seoul"),
        ("2026-10-30T18:00:00+00:00", "Asia/Seoul"),
        ("2026-10-30T18:00:00+09:00", "Fake/Zone"),
    ]:
        with pytest.raises(ValueError):
            validate_opportunity(
                {"actual_outputs": ["report"], "deadline_at": deadline, "deadline_timezone": tz}, set()
            )


def assessment_payload(required=None):
    return {
        "eligibility": required or [],
        "fit": {"level": "HIGH", "reason": "direct output", "source_ids": ["jd"]},
        "career_value": {"level": "UNKNOWN", "reason": "unverified", "source_ids": []},
        "action_priority": {"level": "HIGH", "reason": "ready", "source_ids": ["jd"]},
        "selection_risks": [],
        "preparation_cost": "NOW",
        "recommendation": "PROCEED",
        "main_fix": "verify eligibility",
    }


def test_eligibility_failure_cannot_be_hidden_by_high_fit(flow):
    f, w, _ = flow
    opportunity = f.artifact(w.id, "OpportunityBrief")
    opportunity.data = {
        **opportunity.data,
        "posting_status": "OPEN",
        "required": [{"requirement": "license", "source_id": "jd"}],
    }
    assessment = assess(
        f,
        w.id,
        assessment_payload([{"requirement": "license", "status": "NOT_MET", "reason": "not obtained"}]),
    )
    assert assessment.data["fit"]["level"] == "HIGH"
    assert assessment.data["recommendation"] == "SKIP"
    assert assessment.data["human_decision"] == "PENDING" and w.state == "WAITING_STRATEGY_APPROVAL"
    decision = decide(f, w.id, assessment.id, "HOLD")
    assert decision["artifact_id"] == assessment.id and w.state != "SUBMITTED"
    with pytest.raises(ValueError):
        decide(f, w.id, "previous-version", "PROCEED")


def test_unknown_posting_and_profile_cannot_be_auto_qualified(flow):
    f, w, _ = flow
    assessment = assess(f, w.id, assessment_payload())
    assert assessment.data["recommendation"] == "LOW_PRIORITY"
    opportunity = f.artifact(w.id, "OpportunityBrief")
    opportunity.data = {**opportunity.data, "required": [{"requirement": "degree", "source_id": "jd"}]}
    with pytest.raises(ValueError):
        assess(f, w.id, assessment_payload())
    with pytest.raises(ValueError):
        assess(
            f,
            w.id,
            assessment_payload(
                [{"requirement": "degree", "status": "MET", "reason": "guess", "profile_keys": []}]
            ),
        )


def patch_payload(e, old, new):
    preview = e.body.replace(old, new, 1)
    return {
        "old_text": old,
        "new_text": new,
        "claims": [{**doc(e)["claims"][0], "text": preview}],
        "issue_codes": [],
    }


def test_revision_is_previewed_and_requires_acceptance(flow):
    f, w, e = flow
    q = finish(f, w, e)
    before = f.artifact(w.id, "Draft", q["id"])
    proposal = propose_patch(f, w.id, q["id"], patch_payload(e, "정확도", "실험 정확도"))
    assert f.artifact(w.id, "Draft", q["id"]).id == before.id
    result = resolve(f, w.id, proposal["id"], "ACCEPT")
    current = f.artifact(w.id, "Draft", q["id"])
    assert current.id == result["artifact"]["id"] and current.status == "ACTIVE"
    assert "실험 정확도" in current.data["text"]
    previous_review = latest(f.db, f.user, w.id, "Review", q["id"])
    assert previous_review is not None and previous_review.status == "STALE"
    assert resolve(f, w.id, proposal["id"], "ACCEPT") == result
    f.db.flush()  # persisted receipt must be JSON serializable


def test_reject_or_stale_proposal_never_changes_document(flow):
    f, w, e = flow
    q = finish(f, w, e)
    proposal = propose_patch(f, w.id, q["id"], patch_payload(e, "정확도", "실험 정확도"))
    before = f.artifact(w.id, "Draft", q["id"])
    assert resolve(f, w.id, proposal["id"], "REJECT")["status"] == "REJECTED"
    assert f.artifact(w.id, "Draft", q["id"]).id == before.id
    next_proposal = propose_patch(f, w.id, q["id"], patch_payload(e, "정확도", "실험 정확도"))
    f.patch_document(w.id, q["id"], "정확도", "평가 정확도")
    with pytest.raises(ValueError, match="원문이 바뀌"):
        resolve(f, w.id, next_proposal["id"], "ACCEPT")


def test_human_edited_patch_does_not_inherit_claim_support(flow):
    f, w, e = flow
    q = finish(f, w, e)
    proposal = propose_patch(f, w.id, q["id"], patch_payload(e, "정확도", "실험 정확도"))
    resolve(f, w.id, proposal["id"], "ACCEPT", "테스트 정확도")
    current = f.artifact(w.id, "Draft", q["id"])
    assert all(c["support"] == "NEEDS_REVIEW" for c in current.data["claims"])


def test_chat_edit_produces_reviewable_proposal(flow):
    f, w, e = flow
    q = finish(f, w, e)
    before = f.artifact(w.id, "Draft", q["id"])
    f.provider = FakeLLMProvider(
        {
            "conversation_router": {
                "reply": "",
                "action": "patch",
                "old_text": "정확도",
                "new_text": "테스트 정확도",
            }
        }
    )
    turn = converse(
        f,
        w.id,
        ChatRequest(
            text="정확도를 테스트 정확도로 고쳐",
            client_id="reviewable-edit",
            question_id=q["id"],
            artifact_id=before.id,
        ),
    )
    assert turn["data"]["response"]["status"] == "WAITING_REVIEW"
    assert turn["data"]["response"]["proposal_id"]
    assert f.artifact(w.id, "Draft", q["id"]).id == before.id


def extraction_payload():
    return {
        "items": [
            {
                "kind": "Ownership",
                "quote": "직접 실험을 설계",
                "payload_json": json.dumps({"implementation": "USER"}),
            },
            {
                "kind": "ClaimBoundary",
                "quote": "정확도 80%",
                "payload_json": json.dumps(
                    {"forbidden_claim": "actual deployment", "safe_claim": "experiment", "rationale": "scope"}
                ),
            },
        ],
        "missing_information": ["실제 배포 여부"],
    }


def test_extraction_allows_selective_human_edit_and_keeps_provenance(flow):
    f, _, e = flow
    proposal = propose(f, e.id, extraction_payload())
    choices = [
        {
            "index": 0,
            "data": {
                **proposal["data"]["items"][0]["data"],
                "implementation": "USER_AI_ASSISTED",
                "source_id": "forged",
            },
        }
    ]
    ids = apply(f, proposal["id"], True, choices)
    assert len(ids) == 1
    item = f.db.get(OwnershipRecord, ids[0])
    assert item.data["implementation"] == "USER_AI_ASSISTED" and item.source_id != "forged"
    assert apply(f, proposal["id"], True, choices) == ids
    with pytest.raises(ValueError):
        apply(f, proposal["id"], True, [{"index": 1}])


def test_extraction_stale_or_rejected_proposal_is_not_applied(flow):
    f, _, e = flow
    proposal = propose(f, e.id, extraction_payload())
    e.data = {**e.data, "ownership": {"implementation": "TEAM"}}
    with pytest.raises(ValueError, match="바뀌"):
        apply(f, proposal["id"], True)
    assert apply(f, proposal["id"], False, decision="REJECT") == []
    assert f.db.get(Record, proposal["id"]).data["status"] == "REJECTED"


def test_resume_file_qa_is_bound_to_version_and_master_is_derived(flow):
    f, w, e = flow
    f.approve_strategy(w.id)
    install_refs(f.db)
    resume = f.resume(w.id, doc(e))
    f.review(w.id, resume=True, manual_verified=True)
    with pytest.raises(ValueError, match="실제 파일"):
        f.final_lock(w.id, resume=True)
    confirm_file_qa(f, w.id, resume.id, True)
    f.final_lock(w.id, resume=True)
    save_master(f, resume.id)
    master, ident = master_context(f, [e.id])
    assert ident is None and master["mode"] == "TAILOR_APPROVED_MASTER"
    empty, _ = master_context(f, [])
    assert empty["sections"] == []
    f.patch_document(w.id, "", "정확도", "테스트 정확도", resume=True)
    assert master_context(f, [e.id])[0]["mode"] == "BUILD_FROM_CURRENT_CONFIRMED_FACTS"


def test_latest_explicit_metric_correction_blocks_old_raw_result(db):
    raw, _ = register_source(db, "a", "raw", "80%", "RAW_RESULT")
    correction, _ = register_source(db, "a", "correction", "This number is wrong", "USER_CORRECTION")
    old = add_fact(db, "a", raw.id, "metric", "accuracy", {"value": 80})
    new = add_fact(db, "a", correction.id, "metric", "accuracy", {"value": 90})
    assert old.status == new.status == "CONFLICTED"
    assert "metric:accuracy" not in canonical(db, "a")
    another, _ = register_source(db, "a", "raw-again", "80%", "RAW_RESULT")
    later = add_fact(db, "a", another.id, "metric", "accuracy", {"value": 80})
    assert later.status == "CONFLICTED"
    resolve_fact_conflict(db, "a", new.id, True)
    assert canonical(db, "a")["metric:accuracy"]["value"] == {"value": 90}
    assert old.status == later.status == "SUPERSEDED"


def test_critical_gap_limits_fit_and_deadline_does_not_change_career_value(flow):
    f, w, _ = flow
    opportunity = f.artifact(w.id, "OpportunityBrief")
    opportunity.data = {
        **opportunity.data,
        "posting_status": "OPEN",
        "output_importance": [{"output": "평가 보고서", "importance": "CRITICAL"}],
        "deadline_at": "2099-01-01T18:00:00+09:00",
    }
    pack = f.artifact(w.id, "EvidencePack")
    pack.data = {**pack.data, "uncovered_outputs": ["평가 보고서"]}
    assessment = assess(f, w.id, assessment_payload())
    assert assessment.data["fit"]["level"] == "MEDIUM" and assessment.data["critical_gaps"]
    assert assessment.data["career_value"]["level"] == "UNKNOWN"
    assert rankings(f.db, f.user)["action_order"][0]["workspace_id"] == w.id
    assert rankings(f.db, "other-user")["fit_order"] == []


def test_unmeasured_operational_value_cannot_become_business_impact(flow):
    f, w, e = flow
    f.approve_strategy(w.id)
    q = question(f, w, e)
    brief = f.artifact(w.id, "QuestionBrief", q["id"])
    with pytest.raises(ValueError, match="실제 운영"):
        f.question_brief(w.id, q["id"], {**brief.data, "value_scope": "MEASURED_BUSINESS_IMPACT"})


def test_supplemental_rules_keep_fast_mode_in_human_loop(flow):
    f, w, _ = flow
    install_refs(f.db)
    w.mode = "FAST"
    brief = f.artifact(w.id, "ApplicationBrief")
    f.strategy(w.id, brief.data)
    assert w.state == "WAITING_STRATEGY_APPROVAL"


def test_new_assessment_does_not_reuse_previous_human_decision(flow):
    f, w, _ = flow
    assessment = assess(f, w.id, assessment_payload())
    decide(f, w.id, assessment.id, "HOLD")
    assert rankings(f.db, f.user)["action_order"][0]["decision"] == "HOLD"
    assess(f, w.id, assessment_payload())
    assert rankings(f.db, f.user)["action_order"][0]["decision"] == "PENDING"


def test_strategy_uses_current_assessment_and_decision_changes_stale_it(flow):
    f, w, _ = flow
    assessment = assess(f, w.id, assessment_payload())
    decide(f, w.id, assessment.id, "PROCEED")
    previous = deepcopy(f.artifact(w.id, "ApplicationBrief").data)
    context = {}

    class Provider:
        last_trace = {"model": "fixture"}

        def structured(self, stage, inputs, schema):
            context.update(inputs)
            return schema.model_validate(previous)

    f.provider = Provider()
    strategy = f.strategy(w.id)
    assert context["opportunity_assessment"]["fit"] == assessment.data["fit"]
    assert context["human_decision"] == "PROCEED" and assessment.id in strategy.depends_on
    decide(f, w.id, assessment.id, "HOLD")
    assert strategy.status == "STALE" and w.state == "NEED_USER_ACTION"
