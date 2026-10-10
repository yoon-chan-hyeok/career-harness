# ruff: noqa: F811 -- real workflow fixture
from copy import deepcopy

import pytest
from career.schemas import EvidenceItem
from career.validation import hard_qa
from test_workflow import doc, flow, question  # noqa: F401


def test_current_company_fact_has_its_own_ledger_source_and_frozen_defense(flow):
    service, ws, evidence = flow
    statement = "회사는 2026년에 분석 조직을 신설했습니다."
    source = {"id": "official-company", "url": "https://example.com/careers", "title": "Official careers", "published_at": "2026-09-01", "retrieved_at": "2026-10-02"}
    fact = {"statement": statement, "source_id": source["id"], "source_type": "OFFICIAL", "published_at": source["published_at"], "retrieved_at": source["retrieved_at"], "freshness": "CURRENT"}
    pack = service.artifact(ws.id, "EvidencePack")
    strategy = deepcopy(service.artifact(ws.id, "ApplicationBrief").data)
    research = service.research(ws.id, manual={"official_facts": [fact], "external_evidence": [], "role_signals": [], "historical_jd_signals": [], "selection_process_signals": [], "inferences": [], "sources": [source]})
    from career.research_workspace import decision

    decision(service, ws.id, {"research_id": research.id, "mode": "INSUFFICIENT",
        "limitation": "조직 신설 사실은 확인했으나 이 직무의 내부 채용 사유는 미확인입니다.", "confirmed": True})
    service.analyze(ws.id, {"actual_outputs": ["평가 보고서"], "base_profession": "평가 연구원"})
    service.map_evidence(ws.id, {"items": [{k: v for k, v in pack.data["items"][0].items() if k in EvidenceItem.model_fields}], "uncovered_outputs": []})
    # Derived assessment bookkeeping is not a caller-authored strategy field.
    strategy = {k: v for k, v in strategy.items() if k not in {"opportunity_assessment_id", "opportunity_decision"}}
    from career.schemas import ApplicationBrief
    service.strategy(ws.id, {k: v for k, v in strategy.items() if k in ApplicationBrief.model_fields})
    service.approve_strategy(ws.id)
    q = question(service, ws, evidence)
    service.approve_question(ws.id, q["id"])
    document = doc(evidence)
    document["text"] += "\n" + statement
    company_claim = {"text": statement, "type": "FACT", "evidence_ids": [], "company_source_ids": [source["id"]], "support": "SUPPORTED", "ownership_ok": True}
    document["claims"].append(company_claim)
    draft = service.draft(ws.id, q["id"], document)
    review = service.review(ws.id, q["id"], manual_verified=True)
    assert not review.data["issues"]
    with pytest.raises(ValueError, match="회사 사실"):
        service.validate_ledger({**draft.data, "claims": [dict(company_claim, type="METRIC")]}, service.selected([evidence.id]))
    with pytest.raises(ValueError, match="회사 사실"):
        service.validate_ledger({**draft.data, "claims": [dict(company_claim, company_source_ids=["other-account-source"])]}, service.selected([evidence.id]))
    current_facts = service.artifact(ws.id, "OpportunityBrief").data["company_facts"]
    issues = hard_qa(statement + "\n제가 2026개의 실험을 수행했습니다.", service.selected([evidence.id]), company_facts=current_facts)
    assert any(issue["code"] == "UNSUPPORTED_METRIC" for issue in issues)
    service.final_lock(ws.id, q["id"])
    from final_review_fixture import confirm_final

    confirm_final(service, ws.id)
    service.ready(ws.id)
    bundle = service.freeze(ws.id)
    handoff = service.handoff(ws.id)
    defense = handoff.data["claim_defense"][-1]["company_defense_sources"][0]
    assert defense["source"]["url"] == source["url"]
    assert defense["statement"] == statement
    assert handoff.depends_on == [bundle.id]


def test_dated_company_fact_cannot_become_current_or_personal_numeric_support(flow):
    service, _, evidence = flow
    statement = "Archived result 2024"
    claim = {"text": statement, "type": "FACT", "evidence_ids": [], "company_source_ids": ["missing"], "support": "SUPPORTED", "ownership_ok": True}
    with pytest.raises(ValueError, match="회사 사실"):
        service.validate_ledger({"text": statement, "claims": [claim]}, service.selected([evidence.id]))
    issues = hard_qa(statement, service.selected([evidence.id]), company_facts=[{"statement": statement, "source_id": "archive", "freshness": "DATED"}])
    assert any(issue["code"] == "UNSUPPORTED_METRIC" for issue in issues)
