"""Private I05 candidate index, bounded code-rule evaluation and actual execution proof.

This does not promote learned writing rules, publish global rules or attest source books.
"""

import csv
import hashlib
import json
import os
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator
from sqlalchemy import select

from career.artifacts import fresh, latest, save
from career.guide_choices import Digest, _replay
from career.models import Artifact
from career.question_contracts import Contract, fingerprint
from career.schemas import Document
from career.validation import hard_qa

Id = Annotated[str, Field(min_length=1, max_length=200)]
Action = Literal["CHECK_METRICS", "CHECK_OWNERSHIP", "CHECK_LENGTH"]
ACTION_CODES = {
    "CHECK_METRICS": {"UNSUPPORTED_METRIC", "METRIC_CONFLICT", "METRIC_SCOPE"},
    "CHECK_OWNERSHIP": {"OWNERSHIP", "CLAIM_BOUNDARY"},
    "CHECK_LENGTH": {"CHAR_LIMIT", "EMPTY"},
}
GATES = {"CHECK_METRICS": "SUPPORTED_METRICS", "CHECK_OWNERSHIP": "SCOPED_OWNERSHIP", "CHECK_LENGTH": "CURRENT_LENGTH"}


def allowed(user):
    return os.getenv("CAREER_RULE_PILOT_ENABLED", "0") == "1" and user == os.getenv("CAREER_RULE_PILOT_USER_ID", "")


def load_index(path: Path):
    if path.stat().st_size > 4_000_000:
        raise ValueError("규칙 인덱스가 너무 큽니다.")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    required = {"rule_id", "source_domain", "source_package", "original_rule_summary",
                "has_unapproved_52_evidence_output_hold_candidate", "is_unrefined_65"}
    result, seen = [], set()
    for row in rows:
        if (not required <= row.keys() or any(not isinstance(row[key], str) for key in required)
                or None in row or not row["rule_id"].strip() or row["rule_id"] in seen
                or len(row["original_rule_summary"]) > 16000):
            raise ValueError("규칙 인덱스의 ID·중복·필드를 확인해 주세요.")
        flags = [row[key] for key in ("has_unapproved_52_evidence_output_hold_candidate", "is_unrefined_65")]
        if any(value not in {"YES", "NO"} for value in flags):
            raise ValueError("규칙 인덱스의 미승인·미정밀화 표시가 잘못되었습니다.")
        seen.add(row["rule_id"])
        result.append({"rule_id": row["rule_id"], "source_domain": row["source_domain"],
            "source_package": row["source_package"], "summary": row["original_rule_summary"],
            "candidate_52": flags[0] == "YES", "unrefined_65": flags[1] == "YES",
            "row_hash": fingerprint(row), "activation": "DISABLED", "source_map": "UNVERIFIED",
            "evaluation": "NOT_RUN", "global_publish": "NOT_AUTHORIZED"})
    if not result:
        raise ValueError("규칙 인덱스가 비어 있습니다.")
    return result


class RuleCase(Contract):
    case_id: Id
    document: Document
    evidence: tuple[dict, ...] = Field(max_length=20)
    limit: Annotated[int, Field(strict=True, gt=0, le=100000)]
    expected_codes: tuple[Id, ...]
    profile: dict = Field(default_factory=dict)
    company_facts: tuple[dict, ...] = ()


class AtomicRule(Contract):
    rule_id: Id
    version: Annotated[int, Field(strict=True, gt=0)]
    source_file: Id
    source_sha256: Digest
    start_line: Annotated[int, Field(strict=True, gt=0)]
    end_line: Annotated[int, Field(strict=True, gt=0)]
    excerpt_sha256: Digest
    legacy_heading_id: str | None = Field(default=None, max_length=200)
    scope: Literal["COVER", "RESUME"]
    trigger: Literal["ALWAYS", "HAS_NUMBERS", "HAS_OWNERSHIP_CLAIM"]
    required_evidence: tuple[Literal["CURRENT_EVIDENCE", "CLAIM_LEDGER", "CURRENT_LENGTH"], ...] = Field(min_length=1)
    action: Action
    gate: Literal["SUPPORTED_METRICS", "SCOPED_OWNERSHIP", "CURRENT_LENGTH"]
    expected_output: Literal["RULE_CHECK"]
    stop_condition: Literal["BLOCK_ON_VIOLATION"]
    exception: Literal["NONE"]
    cases: tuple[RuleCase, ...] = Field(min_length=2, max_length=40)

    @model_validator(mode="after")
    def bounded_contract(self):
        if self.gate != GATES[self.action] or self.end_line < self.start_line:
            raise ValueError("규칙의 출처 행·실행·게이트 계약이 맞지 않습니다.")
        if len({c.case_id for c in self.cases}) != len(self.cases):
            raise ValueError("같은 검증 사례를 중복 계산할 수 없습니다.")
        if not any(not c.expected_codes for c in self.cases) or not any(c.expected_codes for c in self.cases):
            raise ValueError("허용·차단 사례를 함께 준비해 주세요.")
        if any(not set(c.expected_codes) <= ACTION_CODES[self.action] for c in self.cases):
            raise ValueError("규칙 검증의 기대 코드가 실행 범위를 벗어났습니다.")
        return self


class Catalog(Contract):
    contracts: tuple[AtomicRule, ...] = Field(default=(), max_length=30)


class RuleRequest(Contract):
    expected_revision: Digest
    rule_id: Id
    rule_version: Annotated[int, Field(strict=True, gt=0)]


class HumanRequest(RuleRequest):
    confirmed: bool = Field(strict=True)

    @model_validator(mode="after")
    def human_confirmation(self):
        if not self.confirmed:
            raise ValueError("출처·계약·검증 결과와 적용 범위를 직접 확인해 주세요.")
        return self


class DocumentRequest(Contract):
    expected_revision: Digest
    document_id: Id
    document_version: Annotated[int, Field(strict=True, gt=0)]


def implementation_hash():
    root = Path(__file__).parent
    return fingerprint({name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                        for name in ("rule_pilot.py", "validation.py", "document_qa.py", "quantities.py")})


def catalog():
    index_path = os.getenv("CAREER_RULE_INDEX_PATH")
    contracts_path = os.getenv("CAREER_RULE_CONTRACTS_PATH")
    try:
        rows = load_index(Path(index_path)) if index_path else []
        if contracts_path and Path(contracts_path).stat().st_size > 2_000_000:
            raise ValueError()
        contracts = Catalog.model_validate(json.loads(Path(contracts_path).read_text("utf-8-sig"))).contracts if contracts_path else ()
        if len({c.rule_id for c in contracts}) != len(contracts):
            raise ValueError()
        return rows, {c.rule_id: c for c in contracts}, "CONFIGURED" if index_path else "EMPTY"
    except (OSError, ValueError, KeyError):
        return [], {}, "UNAVAILABLE"


def source_proof(row, contract):
    configured_root = os.getenv("CAREER_RULE_SOURCE_ROOT", "")
    if not configured_root or not Path(configured_root).is_absolute():
        raise ValueError("규칙 원문 전용 폴더의 절대 경로가 필요합니다.")
    root = Path(configured_root).resolve()
    target = (root / contract.source_file).resolve()
    if (not target.is_relative_to(root) or target == root or target.suffix.lower() not in {".md", ".txt", ".csv"}
            or target.stat().st_size > 2_000_000):
        raise ValueError("원문 출처 경로·크기를 확인해 주세요.")
    raw = target.read_bytes()
    lines = raw.decode("utf-8-sig").splitlines()
    if contract.end_line > len(lines):
        raise ValueError("실제 원문의 행 위치를 대조해 주세요.")
    excerpt = "\n".join(lines[contract.start_line - 1:contract.end_line])
    if (hashlib.sha256(raw).hexdigest() != contract.source_sha256
            or hashlib.sha256(excerpt.encode()).hexdigest() != contract.excerpt_sha256):
        raise ValueError("원문 또는 출처 구간이 바뀌었습니다. 다시 대조해 주세요.")
    proof = fingerprint([row["row_hash"], contract.model_dump(mode="json"), contract.source_sha256,
                         contract.excerpt_sha256, implementation_hash()])
    return proof, excerpt


def snapshot(service, workspace, *, _internal=False):
    service.ws(workspace)
    rows, contracts, availability = catalog()
    saved = {}
    for record in service.db.scalars(select(Artifact).where(Artifact.user_id == service.user,
            Artifact.workspace_id == workspace, Artifact.kind.in_(["RuleSourceReview", "RuleCodeEvaluation", "RuleActivation"]))
            .order_by(Artifact.version)):
        saved[(record.kind, record.slot)] = record
    items = []
    for row in rows:
        contract = contracts.get(row["rule_id"])
        proof, excerpt, issue = None, None, None
        if contract and not row["candidate_52"] and not row["unrefined_65"]:
            try:
                proof, excerpt = source_proof(row, contract)
            except (OSError, ValueError, UnicodeError):
                issue = "현재 원문·출처 구간 확인이 필요합니다."
        elif contract:
            issue = "52개 보정 후보·65개 미정밀화 항목은 이 pilot에서 활성화할 수 없습니다."
        states = {}
        for kind in ("RuleSourceReview", "RuleCodeEvaluation", "RuleActivation"):
            record = saved.get((kind, row["rule_id"]))
            current = False
            if record:
                try:
                    fresh(service.db, service.user, record)
                    current = bool(proof and record.data.get("proof") == proof)
                except (ValueError, LookupError):
                    pass
            states[kind] = {"id": record.id, "version": record.version, "current": current,
                            "data": record.data} if record else None
        items.append({**row, "contract": contract.model_dump(mode="json", exclude={"cases"}) if contract else None,
                      "proof": proof, "excerpt": excerpt, "issue": issue, "states": states})
    known = {row["rule_id"] for row in rows}
    orphans = [{"rule_id": row.slot, "rule_version": row.data["rule_version"], "activation_id": row.id}
               for (kind, _), row in saved.items() if kind == "RuleActivation"
               and row.slot not in known and row.data.get("activation") == "ACTIVE_SCOPED"]
    revision = fingerprint([availability, items, orphans, implementation_hash()])
    result = {"workspace_id": workspace, "availability": availability, "revision": revision, "rules": items,
            "counts": {"indexed": len(rows), "candidate_52": sum(r["candidate_52"] for r in rows),
                       "unrefined_65": sum(r["unrefined_65"] for r in rows)},
            "linked_historical_20": "NOT_RUN", "specified_gates_25": "NOT_RUN",
            "unavailable_adoptions": orphans,
            "global_publish": "NOT_AUTHORIZED", "can_execute": False}
    if _internal:
        result["_contracts"] = contracts
    return result


def current_rule(service, workspace, request):
    state = snapshot(service, workspace, _internal=True)
    row = next((r for r in state["rules"] if r["rule_id"] == request.rule_id), None)
    if (request.expected_revision != state["revision"] or row is None or not row["proof"]
            or not row["contract"] or row["contract"]["version"] != request.rule_version):
        raise ValueError("현재 출처·규칙 계약·버전을 다시 확인해 주세요.")
    return row, state["_contracts"][request.rule_id]


def review_source(service, workspace, request: HumanRequest, request_id):
    service.editable(service.ws(workspace))
    previous, request_hash = _replay(service, workspace, request.rule_id, "RuleSourceReview", request_id, request)
    if previous:
        return previous
    row, _ = current_rule(service, workspace, request)
    return save(service.db, service.user, workspace, "RuleSourceReview", {
        "proof": row["proof"], "rule_id": request.rule_id, "rule_version": request.rule_version,
        "source_map": "HUMAN_ATTESTED_PRIVATE", "global_publish": "NOT_AUTHORIZED", "actor_id": service.user,
        "request_id": request_id, "request_hash": request_hash}, slot=request.rule_id)[0]


def check(action, document, evidence, limit, profile=None, company_facts=()):
    return [issue for issue in hard_qa(document["text"], list(evidence), limit, document=document,
                                      profile=profile, company_facts=company_facts)
            if issue["code"] in ACTION_CODES[action]]


def evaluate(service, workspace, request: RuleRequest, request_id):
    service.editable(service.ws(workspace))
    previous, request_hash = _replay(service, workspace, request.rule_id, "RuleCodeEvaluation", request_id, request)
    if previous:
        return previous
    row, contract = current_rule(service, workspace, request)
    review = row["states"]["RuleSourceReview"]
    if not review or not review["current"]:
        raise ValueError("실제 원문 구간과 규칙 연결을 먼저 직접 확인해 주세요.")
    results = []
    for case in contract.cases:
        issues = check(contract.action, case.document.model_dump(), case.evidence, case.limit, case.profile, case.company_facts)
        actual = sorted({i["code"] for i in issues})
        results.append({"case_id": case.case_id, "input_hash": fingerprint(case.model_dump(mode="json")),
                        "actual_codes": actual, "expected_codes": sorted(case.expected_codes),
                        "passed": actual == sorted(case.expected_codes)})
    return save(service.db, service.user, workspace, "RuleCodeEvaluation", {
        "proof": row["proof"], "rule_id": request.rule_id, "rule_version": request.rule_version,
        "evaluation_kind": "CODE_EXECUTED_NOT_LLM", "implementation_hash": implementation_hash(),
        "status": "PASSED" if all(r["passed"] for r in results) else "FAILED", "results": results,
        "checks_executed": len(results), "linked_historical_20": "NOT_RUN", "specified_gates_25": "NOT_RUN",
        "request_id": request_id, "request_hash": request_hash}, deps=[review["id"]], slot=request.rule_id)[0]


def activate(service, workspace, request: HumanRequest, request_id):
    service.editable(service.ws(workspace))
    previous, request_hash = _replay(service, workspace, request.rule_id, "RuleActivation", request_id, request)
    if previous:
        return previous
    row, _ = current_rule(service, workspace, request)
    review, evaluation = row["states"]["RuleSourceReview"], row["states"]["RuleCodeEvaluation"]
    if not review or not review["current"] or not evaluation or not evaluation["current"] or evaluation["data"]["status"] != "PASSED":
        raise ValueError("현재 버전의 출처 확인·실제 코드 검증 통과와 적용 범위 승인이 필요합니다.")
    return save(service.db, service.user, workspace, "RuleActivation", {
        "proof": row["proof"], "rule_id": request.rule_id, "rule_version": request.rule_version,
        "activation": "ACTIVE_SCOPED", "owner_id": service.user, "workspace_id": workspace,
        "scope": row["contract"]["scope"], "global_publish": "NOT_AUTHORIZED",
        "request_id": request_id, "request_hash": request_hash}, deps=[review["id"], evaluation["id"]], slot=request.rule_id)[0]


def document_revision(service, workspace, document):
    from career.models import Source
    from career.truth import canonical, owned

    selected = service.selected(document.data["selected_evidence_ids"])
    evidence = [{key: row[key] for key in ("id", "source_id", "status", "kind", "title", "body", "data", "context_source_ids")}
                for row in selected]
    profile = {key: {field: row[field] for field in ("id", "source_id", "status", "value", "fact_type")}
               for key, row in canonical(service.db, service.user).items()}
    sources = []
    for ident in sorted({ident for row in selected for ident in row["context_source_ids"]}):
        source = owned(service.db, Source, service.user, ident)
        sources.append([source.id, source.content_hash, source.status, source.authority])
    return fingerprint([document.id, document.version, document.data, evidence, profile, sources,
        snapshot(service, workspace)["revision"]])


def adopted(service, workspace):
    current = {}
    for record in service.db.scalars(select(Artifact).where(Artifact.user_id == service.user,
            Artifact.workspace_id == workspace, Artifact.kind == "RuleActivation").order_by(Artifact.version)):
        current[record.slot] = record
    return [r for r in current.values() if r.data.get("activation") == "ACTIVE_SCOPED"]


def retire(service, workspace, request: HumanRequest, request_id):
    service.editable(service.ws(workspace))
    previous, request_hash = _replay(service, workspace, request.rule_id, "RuleRetirement", request_id, request)
    if previous:
        return previous
    state = snapshot(service, workspace)
    old = latest(service.db, service.user, workspace, "RuleActivation", request.rule_id)
    assert old is not None
    if request.expected_revision != state["revision"] or old.data["rule_version"] != request.rule_version:
        raise ValueError("현재 채택한 규칙 버전을 다시 확인해 주세요.")
    save(service.db, service.user, workspace, "RuleActivation", {
        "activation": "RETIRED", "rule_id": request.rule_id, "rule_version": request.rule_version}, slot=request.rule_id)
    return save(service.db, service.user, workspace, "RuleRetirement", {
        "rule_id": request.rule_id, "rule_version": request.rule_version,
        "request_id": request_id, "request_hash": request_hash}, slot=request.rule_id)[0]


def execute(service, workspace, document, evidence, limit, *, request_id=None, request_hash=None):
    """Called with actual owned current document/evidence; a POST cannot supply a verdict."""
    from career.quantities import numeric_tokens
    from career.truth import canonical

    state = snapshot(service, workspace, _internal=True)
    contracts = state["_contracts"]
    records, issues = [], []
    known = {r["rule_id"] for r in state["rules"]}
    for missing in adopted(service, workspace):
        if missing.slot not in known:
            issues.append({"code": "RULE_RECONFIRM", "priority": "P1", "message": "채택한 규칙의 인덱스·출처를 확인할 수 없습니다."})
            records.append({"rule_id": missing.slot, "verdict": "BLOCKED_BY_POLICY", "events": []})
    for row in state["rules"]:
        activation = row["states"]["RuleActivation"]
        if not activation:
            continue
        if activation["data"].get("activation") != "ACTIVE_SCOPED":
            continue
        if not activation["current"]:
            issues.append({"code": "RULE_RECONFIRM", "priority": "P1", "message": "채택한 규칙의 출처·검증을 다시 확인해 주세요."})
            records.append({"rule_id": row["rule_id"], "verdict": "BLOCKED_BY_POLICY", "events": []})
            continue
        contract = contracts[row["rule_id"]]
        domain = "RESUME" if document.kind == "ResumeContent" else "COVER"
        if domain != contract.scope:
            continue
        triggered = contract.trigger == "ALWAYS" or (contract.trigger == "HAS_NUMBERS" and bool(numeric_tokens(document.data["text"]))) or (
            contract.trigger == "HAS_OWNERSHIP_CLAIM" and any(c["type"] == "OWNERSHIP" for c in document.data["claims"]))
        events = [{"kind": "SELECTED", "contract_proof": row["proof"]}]
        if not triggered:
            records.append({"rule_id": row["rule_id"], "verdict": "SELECTED_NOT_TRIGGERED", "events": events})
            continue
        precondition_failed = ("CURRENT_EVIDENCE" in contract.required_evidence and not evidence) or (
                "CLAIM_LEDGER" in contract.required_evidence and not document.data.get("claims"))
        if precondition_failed:
            codes = [{"code": "RULE_REQUIRED_EVIDENCE", "priority": "P0", "message": "규칙 실행에 필요한 현재 근거·Claim Ledger가 없습니다."}]
        else:
            codes = check(contract.action, document.data, evidence, limit,
                          canonical(service.db, service.user), service.artifact(workspace, "OpportunityBrief").data.get("company_facts", []))
        output_hash = fingerprint([i["code"] for i in codes])
        events.extend([{"kind": "PRECONDITION_BLOCKED" if precondition_failed else "ACTION", "action": contract.action, "output_hash": output_hash},
                       {"kind": "GATE", "gate": contract.gate, "verdict": "FAIL" if codes else "PASS", "output_hash": output_hash}])
        records.append({"rule_id": row["rule_id"], "rule_version": contract.version,
            "verdict": "BLOCKED_BY_POLICY" if codes else "APPLIED_VERIFIED", "events": events,
            "visible_effect": "BLOCK_REVIEW" if codes else "VERIFIED_EXISTING_BOUNDARY",
            "activation_id": activation["id"], "proof": row["proof"]})
        issues.extend(codes)
    deps = [document.id] + [r["activation_id"] for r in records if r.get("activation_id")]
    result, _ = save(service.db, service.user, workspace, "RuleExecution", {
        "document_id": document.id, "document_version": document.version, "document_hash": fingerprint(document.data),
        "input_revision": document_revision(service, workspace, document), "records": records,
        "platform_safety_gate": "EXISTING_HARD_CHECKS_REMAIN_REQUIRED", "issues": issues,
        "implementation_hash": implementation_hash(), "evaluation_kind": "CODE_EXECUTED_NOT_LLM",
        **({"request_id": request_id, "request_hash": request_hash} if request_id else {})},
        deps=deps, sources=document.source_ids, slot=document.slot)
    return result


def require_checks(service, workspace, document):
    if not adopted(service, workspace):
        return
    if not allowed(service.user):
        raise ValueError("채택한 규칙 검증을 다시 켜고 현재 문서를 검수해 주세요.")
    current = latest(service.db, service.user, workspace, "RuleExecution", document.slot, required=False)
    if current is None:
        raise ValueError("채택한 규칙으로 현재 문서를 먼저 검수해 주세요.")
    fresh(service.db, service.user, current)
    if current.data["input_revision"] != document_revision(service, workspace, document) or current.data["issues"]:
        raise ValueError("규칙의 출처·근거·문서 버전 또는 검증 결과를 다시 확인해 주세요.")
