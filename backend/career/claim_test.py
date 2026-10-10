"""Evidence Test before Claim Lock, with versioned proof and explicit manual mode."""

import json
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from career.artifacts import fresh, latest, save
from career.schemas import Schema
from career.validation import GOOD, hard_qa

if TYPE_CHECKING:
    from career.workflow import Workflow

CHECKS = {
    "DIRECT_PROOF": "주장을 직접 뒷받침하는 근거가 있는가",
    "INTERVIEW_DEFENSE": "과장 없이 면접에서 설명할 수 있는가",
    "STRONGEST_EVIDENCE": "더 강한 근거를 놓치고 있지 않은가",
    "NO_FACT_FITTING": "주장에 맞춰 사실을 바꾸거나 확대하지 않았는가",
}


class Citation(Schema):
    evidence_id: str
    quote: str = Field(min_length=1)
    record_id: str = ""


class ClaimSupport(Schema):
    claim: str = Field(min_length=1)
    support: Literal["SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "NEEDS_VERIFICATION"]
    rationale: str = Field(min_length=1)
    citations: list[Citation]


class EvidenceCheck(Schema):
    key: Literal["DIRECT_PROOF", "INTERVIEW_DEFENSE", "STRONGEST_EVIDENCE", "NO_FACT_FITTING"]
    verdict: Literal["PASS", "FAIL", "NEEDS_VERIFICATION"]
    rationale: str = Field(min_length=1)


class EvidenceTest(Schema):
    claims: list[ClaimSupport] = Field(min_length=1)
    checks: list[EvidenceCheck] = Field(min_length=4, max_length=4)
    followups: list[str]


def claim_texts(brief):
    return list(dict.fromkeys([brief["primary_message"], *brief.get("supporting_claims", [])]))


def validate_citations(evidence: list[dict], citations: list[dict]):
    by_id = {item["id"]: item for item in evidence}
    for citation in citations:
        selected = by_id.get(citation["evidence_id"])
        if selected is None:
            raise ValueError("현재 문항에 선택한 근거만 주장 증명에 사용할 수 있습니다.")
        content = selected["body"]
        if citation.get("record_id"):
            records = selected["data"].get("metric_ledger", []) + [
                {**row["data"], "id": row["id"], "status": row["status"]}
                for key in ("confirmed_decision_episodes", "confirmed_ownership", "confirmed_claim_boundaries")
                for row in selected["data"].get(key, [])
            ]
            record = next((row for row in records if row["id"] == citation["record_id"]
                           and row["status"] in GOOD), None)
            if record is None:
                raise ValueError("인용한 지표·판단·수행 범위의 현재 확인 기록을 찾을 수 없습니다.")
            content = json.dumps(record, ensure_ascii=False)
        if not citation["quote"].strip() or citation["quote"] not in content:
            raise ValueError("인용문은 연결한 현재 원문과 정확히 일치해야 합니다.")


def run(service: "Workflow", workspace: str, qid: str, manual=None, *, confirmed=False):
    ws = service.ws(workspace)
    service.editable(ws)
    brief = service.artifact(workspace, "QuestionBrief", qid)
    strategy = service.artifact(workspace, "ApplicationBrief")
    pack = service.artifact(workspace, "EvidencePack")
    evidence = service.selected(brief.data["evidence_ids"])
    alternatives = service.selected(list(dict.fromkeys(
        item["evidence_id"] for item in pack.data["items"]
        if item["classification"] != "NO_EVIDENCE" and item["evidence_id"] not in brief.data["evidence_ids"]
    )))
    if manual is not None and not confirmed:
        raise ValueError("원문과 네 가지 기준을 직접 대조한 뒤 검증 결과를 저장해 주세요.")
    data = EvidenceTest.model_validate(manual if manual is not None else service.ai(
        "claim_evidence_test", {"question": service.question(workspace, qid), "brief": brief.data,
                                "strategy": strategy.data, "evidence": evidence, "alternatives": alternatives,
                                "required_checks": CHECKS}, EvidenceTest,
    )).model_dump()
    texts = claim_texts(brief.data)
    if {item["claim"] for item in data["claims"]} != set(texts) or len(data["claims"]) != len(texts):
        raise ValueError("현재 핵심 메시지와 뒷받침 주장을 빠짐없이 한 번씩 검증해 주세요.")
    if {item["key"] for item in data["checks"]} != CHECKS.keys():
        raise ValueError("Evidence Test의 네 가지 기준을 모두 대조해 주세요.")
    for claim in data["claims"]:
        if not claim["rationale"].strip():
            raise ValueError("주장과 근거가 연결되는 이유를 기록해 주세요.")
        if claim["support"] == "SUPPORTED" and not claim["citations"]:
            raise ValueError("뒷받침되는 주장에는 선택 근거의 원문 인용이 필요합니다.")
        validate_citations(evidence, claim["citations"])
    if any(not check["rationale"].strip() for check in data["checks"]):
        raise ValueError("네 가지 기준의 판단 이유를 기록해 주세요.")
    issues = hard_qa("\n".join(texts), evidence, limit=20000)
    passed = (not issues and not data["followups"]
              and all(c["support"] == "SUPPORTED" for c in data["claims"])
              and all(c["verdict"] == "PASS" for c in data["checks"]))
    data.update({"result": "PASSED" if passed else "NEEDS_REVISION",
                 "mode": "USER_VERIFIED" if manual is not None else "AI_REVIEWED",
                 "brief_id": brief.id, "brief_version": brief.version, "hard_issues": issues})
    item, _ = save(service.db, service.user, workspace, "ClaimEvidenceTest", data, slot=qid,
                   deps=[brief.id, strategy.id, pack.id],
                   sources=sorted(set(service.reference_sources("claim_evidence_test") + [
                       source for e in evidence + alternatives for source in e["context_source_ids"]])),
                   model="manual" if manual is not None else service.current_model)
    return item


def require_pass(service: "Workflow", workspace: str, qid: str, brief):
    item = latest(service.db, service.user, workspace, "ClaimEvidenceTest", qid, required=False)
    if item is None:
        raise ValueError("메시지 승인 전에 Evidence Test로 주장과 원문 근거를 대조해 주세요.")
    fresh(service.db, service.user, item)
    if (item.data.get("brief_id") != brief.id or item.data.get("brief_version") != brief.version
            or brief.id not in item.depends_on or item.data.get("result") != "PASSED"):
        raise ValueError("현재 문항 메시지의 Evidence Test를 통과한 뒤 승인해 주세요.")
    return item
