"""Source-bound extraction proposals. User confirmation is separate from generation."""

import hashlib
import json
from typing import Literal

from pydantic import Field

from career.db import Record
from career.domain import SCHEMAS, save_entity
from career.models import Evidence, Source
from career.schemas import Schema
from career.truth import owned, register_source, view
from career.validation import GOOD
from career.workflow import Workflow


class ExtractedItem(Schema):
    kind: Literal["Project", "DecisionEpisode", "Metric", "Ownership", "ClaimBoundary"]
    quote: str = Field(min_length=1)
    # Schema-specific payload is encoded to keep the provider's JSON schema closed.
    payload_json: str


class Extraction(Schema):
    items: list[ExtractedItem]
    missing_information: list[str]


class ExtractionRequest(Schema):
    manual: Extraction | None = None


class Selection(Schema):
    index: int = Field(ge=0, strict=True)
    data: dict | None = None


class ExtractionDecision(Schema):
    confirmed: bool = False
    selections: list[Selection] | None = None
    decision: Literal["ACCEPT", "REJECT"] = "ACCEPT"


def evidence_fingerprint(evidence):
    return hashlib.sha256(
        json.dumps([evidence.source_id, evidence.body, evidence.data], sort_keys=True).encode()
    ).hexdigest()


def propose(service: Workflow, evidence_id: str, manual=None):
    evidence = owned(service.db, Evidence, service.user, evidence_id)
    if (
        evidence.kind == "EXPRESSION"
        or owned(service.db, Source, service.user, evidence.source_id).status not in GOOD
    ):
        raise ValueError("유효한 사실 원자료만 구조화할 수 있습니다.")
    parsed = Extraction.model_validate(
        manual
        or service.ai(
            "truth_extraction",
            {
                "task": "Extract ONLY explicit facts. Each quote must be an exact substring of the evidence. Missing metric scope and ownership stay unknown; never infer implementation ownership. Encode a payload matching one of the supplied schemas, excluding source_id/evidence_id (injected by server). Return no item rather than invent required fields.",
                "evidence": evidence.body,
                "schemas": {
                    k: SCHEMAS[k].model_json_schema()
                    for k in ["Project", "DecisionEpisode", "Metric", "Ownership", "ClaimBoundary"]
                },
            },
            Extraction,
        )
    )
    proposals = []
    for item in parsed.items:
        if item.quote not in evidence.body:
            raise ValueError("추출한 항목에 원자료의 정확한 인용 구간이 없습니다.")
        payload = json.loads(item.payload_json)
        payload["source_id"] = evidence.source_id
        if item.kind != "Project":
            payload["evidence_id"] = evidence.id
        if "status" in SCHEMAS[item.kind].model_fields:
            payload["status"] = "UNVERIFIED"
        data = SCHEMAS[item.kind].model_validate(payload).model_dump()
        proposals.append({"kind": item.kind, "quote": item.quote, "data": data})
    record = Record(
        user_id=service.user,
        kind="ExtractionProposal",
        data={
            "source_id": evidence.source_id,
            "evidence_id": evidence.id,
            "items": proposals,
            "missing_information": parsed.missing_information,
            "applied": False,
            "fingerprint": evidence_fingerprint(evidence),
            "status": "PENDING",
        },
    )
    service.db.add(record)
    service.db.flush()
    return view(record)


def apply(service: Workflow, proposal_id: str, confirmed: bool, selections=None, decision="ACCEPT"):
    proposal = owned(service.db, Record, service.user, proposal_id)
    if proposal.kind != "ExtractionProposal" or decision not in {"ACCEPT", "REJECT"}:
        raise ValueError("유효한 경험 제안과 결정을 선택해 주세요.")
    signature = {"selections": selections, "decision": decision}
    if proposal.data.get("status") == "REJECTED":
        if decision != "REJECT":
            raise ValueError("이미 거절한 제안입니다. 새로 구조화해 주세요.")
        return []
    if decision == "REJECT":
        if proposal.data["applied"]:
            raise ValueError("이미 반영한 제안입니다.")
        proposal.data = {**proposal.data, "status": "REJECTED", "resolution": signature}
        return []
    if not confirmed:
        raise ValueError("추출 항목을 읽고 직접 확인한 경우에만 저장할 수 있습니다.")
    if proposal.data["applied"]:
        if proposal.data.get("resolution", signature) != signature:
            raise ValueError("이미 반영한 제안에 다른 항목을 적용할 수 없습니다.")
        return proposal.data["entity_ids"]
    evidence = owned(service.db, Evidence, service.user, proposal.data["evidence_id"])
    if (
        evidence.status not in GOOD
        or owned(service.db, Source, service.user, evidence.source_id).status not in GOOD
    ):
        raise ValueError("경험과 원자료를 먼저 확인해 주세요.")
    if proposal.data.get("fingerprint") != evidence_fingerprint(evidence):
        raise ValueError("구조화 이후 원자료나 수행 범위가 바뀌었습니다. 새로 정리해 주세요.")
    chosen: list[dict] = (
        selections if selections is not None else [{"index": i} for i in range(len(proposal.data["items"]))]
    )
    indices = [s["index"] for s in chosen]
    if (
        not indices
        or len(indices) != len(set(indices))
        or any(i < 0 or i >= len(proposal.data["items"]) for i in indices)
    ):
        raise ValueError("반영할 항목을 중복 없이 선택해 주세요.")
    validated = []
    for choice in chosen:
        item = proposal.data["items"][choice["index"]]
        data = {**(choice.get("data") or item["data"])}
        # Provenance and verification cannot be supplied by the browser.
        data["source_id"] = evidence.source_id
        if item["kind"] != "Project":
            data["evidence_id"] = evidence.id
        if "status" in SCHEMAS[item["kind"]].model_fields:
            data["status"] = "USER_CONFIRMED"
        validated.append((item, SCHEMAS[item["kind"]].model_validate(data).model_dump()))
    ids = []
    for item, data in validated:
        if choice_edit := next(
            (s.get("data") for s in chosen if proposal.data["items"][s["index"]] is item), None
        ):
            if choice_edit != item["data"]:
                source, _ = register_source(
                    service.db,
                    service.user,
                    "extraction-corrections/" + proposal.id,
                    json.dumps(data, ensure_ascii=False, sort_keys=True),
                    "USER_CORRECTION",
                    {
                        "parent_source_id": evidence.source_id,
                        "proposal_id": proposal.id,
                        "quote": item["quote"],
                    },
                )
                data["source_id"] = source.id
        ids.append(save_entity(service.db, service.user, item["kind"], data, explicit_confirmation=True).id)
    proposal.data = {
        **proposal.data,
        "applied": True,
        "status": "ACCEPTED",
        "entity_ids": ids,
        "resolution": signature,
    }
    return ids
