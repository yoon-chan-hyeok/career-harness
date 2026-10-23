# ruff: noqa: F811 -- reusable workflow fixture
import csv
import hashlib
import json

import pytest
from career.artifacts import latest
from career.models import Artifact
from career.rule_pilot import (
    HumanRequest,
    activate,
    adopted,
    catalog,
    evaluate,
    execute,
    load_index,
    require_checks,
    retire,
    review_source,
    snapshot,
)
from career.workflow import Workflow
from sqlalchemy import event, select
from test_workflow import doc, flow, question  # noqa: F401

HEADERS = ["rule_id", "source_domain", "source_package", "original_rule_summary",
           "has_unapproved_52_evidence_output_hold_candidate", "is_unrefined_65", "activation"]


def write_index(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)


def index_row(ident="SYNTHETIC-RULE-1", **changes):
    return {"rule_id": ident, "source_domain": "SYNTHETIC", "source_package": "synthetic-not-nine-books",
            "original_rule_summary": "현재 원문에 없는 수치를 쓰지 않습니다.",
            "has_unapproved_52_evidence_output_hold_candidate": "NO", "is_unrefined_65": "NO", "activation": "DISABLED", **changes}


@pytest.fixture
def pilot(flow, tmp_path, monkeypatch):
    f, w, e = flow
    f.approve_strategy(w.id)
    q = question(f, w, e)
    f.approve_question(w.id, q["id"])
    document = f.draft(w.id, q["id"], doc(e))
    root = tmp_path / "sources"
    root.mkdir()
    raw = "# Synthetic rule\n현재 원문에 없는 수치를 쓰지 않습니다.\n"
    source = root / "synthetic.md"
    source.write_text(raw, encoding="utf-8")
    index = tmp_path / "index.csv"
    write_index(index, [index_row()])
    valid = doc(e)
    invalid = {"text": "정확도 999%를 달성했습니다.", "claims": []}
    cases = [{"case_id": "positive", "document": valid, "evidence": f.selected([e.id]), "limit": 1000, "expected_codes": []},
             {"case_id": "negative", "document": invalid, "evidence": f.selected([e.id]), "limit": 1000, "expected_codes": ["UNSUPPORTED_METRIC"]}]
    cases = json.loads(json.dumps(cases, default=str))
    contract = {"rule_id": "SYNTHETIC-RULE-1", "version": 1, "source_file": "synthetic.md",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "start_line": 2, "end_line": 2,
        "excerpt_sha256": hashlib.sha256(raw.splitlines()[1].encode()).hexdigest(),
        "scope": "COVER", "trigger": "HAS_NUMBERS", "required_evidence": ["CURRENT_EVIDENCE"],
        "action": "CHECK_METRICS", "gate": "SUPPORTED_METRICS", "expected_output": "RULE_CHECK",
        "stop_condition": "BLOCK_ON_VIOLATION", "exception": "NONE", "cases": cases}
    contracts = tmp_path / "contracts.json"
    contracts.write_text(json.dumps({"contracts": [contract]}, ensure_ascii=False, default=str), encoding="utf-8")
    for key, value in {"CAREER_RULE_PILOT_ENABLED": "1", "CAREER_RULE_PILOT_USER_ID": f.user,
                       "CAREER_RULE_INDEX_PATH": str(index), "CAREER_RULE_CONTRACTS_PATH": str(contracts),
                       "CAREER_RULE_SOURCE_ROOT": str(root)}.items():
        monkeypatch.setenv(key, value)
    f.db.commit()
    return f, w, e, q, document, index, source, contracts, contract


def request(f, w, confirmed=True):
    state = snapshot(f, w.id)
    return HumanRequest(expected_revision=state["revision"], rule_id="SYNTHETIC-RULE-1", rule_version=1, confirmed=confirmed)


def activate_rule(pilot):
    f, w, *_ = pilot
    review_source(f, w.id, request(f, w), "review-1")
    result = evaluate(f, w.id, request(f, w), "eval-1")
    assert result.data["status"] == "PASSED", result.data
    return activate(f, w.id, request(f, w), "activation-1")


def test_import_is_read_only_even_if_csv_declares_active_and_246_synthetic_rows_have_no_attestation(tmp_path):
    path = tmp_path / "index.csv"
    write_index(path, [index_row(f"SYN-{i:03}", activation="ACTIVE") for i in range(246)])
    rows = load_index(path)
    assert len(rows) == 246 and all(r["activation"] == "DISABLED" for r in rows)
    assert all(r["source_map"] == "UNVERIFIED" and r["evaluation"] == "NOT_RUN" for r in rows)
    assert all(r["global_publish"] == "NOT_AUTHORIZED" for r in rows)


def test_get_has_only_selects_no_provider_and_preserves_static_20_25_not_run(pilot, monkeypatch):
    f, w, *_ = pilot
    monkeypatch.setattr(Workflow, "ai", lambda *a, **k: pytest.fail("GET called model"))
    def select_only(conn, cursor, statement, parameters, context, executemany):
        assert statement.lstrip().upper().startswith("SELECT")
    event.listen(f.db.get_bind(), "before_cursor_execute", select_only)
    try:
        first = snapshot(f, w.id)
        assert snapshot(f, w.id) == first
        assert not f.db.new and not f.db.dirty
    finally:
        event.remove(f.db.get_bind(), "before_cursor_execute", select_only)
    assert first["linked_historical_20"] == first["specified_gates_25"] == "NOT_RUN"
    assert first["rules"][0]["source_map"] == "UNVERIFIED"
    assert not adopted(f, w.id)


@pytest.mark.parametrize("flag", ["has_unapproved_52_evidence_output_hold_candidate", "is_unrefined_65"])
def test_52_and_65_cannot_enter_active_resolver_even_with_contract(pilot, flag):
    f, w, _, _, _, index, *_ = pilot
    write_index(index, [index_row(**{flag: "YES"})])
    state = snapshot(f, w.id)
    assert state["rules"][0]["proof"] is None
    with pytest.raises(ValueError):
        review_source(f, w.id, request(f, w), "unapproved-source")
    assert not adopted(f, w.id)


def test_source_hash_span_and_legacy_heading_alone_cannot_attest_equivalence(pilot):
    f, w, _, _, _, _, source, contracts, contract = pilot
    contract["legacy_heading_id"] = "cover:1:heading-hash"
    contract["excerpt_sha256"] = "0" * 64
    contracts.write_text(json.dumps({"contracts": [contract]}), encoding="utf-8")
    assert snapshot(f, w.id)["rules"][0]["proof"] is None
    with pytest.raises(ValueError):
        review_source(f, w.id, request(f, w), "bad-span")
    contract["excerpt_sha256"] = hashlib.sha256(source.read_text("utf-8").splitlines()[1].encode()).hexdigest()
    contracts.write_text(json.dumps({"contracts": [contract]}), encoding="utf-8")
    assert snapshot(f, w.id)["rules"][0]["source_map"] == "UNVERIFIED"
    assert latest(f.db, f.user, w.id, "RuleSourceReview", "SYNTHETIC-RULE-1", required=False) is None


def test_source_review_real_code_eval_and_human_activation_are_separate_and_bound(pilot):
    f, w, *_ = pilot
    with pytest.raises(ValueError, match="출처|확인"):
        activate(f, w.id, request(f, w), "too-early")
    reviewed = review_source(f, w.id, request(f, w), "reviewed")
    assert not adopted(f, w.id)
    evaluation = evaluate(f, w.id, request(f, w), "code-evaluation")
    assert evaluation.data["checks_executed"] == 2 and evaluation.data["status"] == "PASSED"
    assert evaluation.data["evaluation_kind"] == "CODE_EXECUTED_NOT_LLM"
    assert "999%" not in str(evaluation.data)
    assert not adopted(f, w.id)
    activation = activate(f, w.id, request(f, w), "approved")
    assert reviewed.id in activation.depends_on and evaluation.id in activation.depends_on
    assert activation.data["activation"] == "ACTIVE_SCOPED" and activation.data["workspace_id"] == w.id
    assert activation.data["global_publish"] == "NOT_AUTHORIZED"


def test_failed_actual_case_cannot_activate_even_if_request_claims_confirmation(pilot):
    f, w, _, _, _, _, _, contracts, contract = pilot
    contract["cases"][1]["document"]["text"] = "정확도 80%를 확인했습니다."
    contracts.write_text(json.dumps({"contracts": [contract]}), encoding="utf-8")
    review_source(f, w.id, request(f, w), "review-failing-case")
    result = evaluate(f, w.id, request(f, w), "run-failing-case")
    assert result.data["status"] == "FAILED"
    with pytest.raises(ValueError, match="통과"):
        activate(f, w.id, request(f, w), "failed-activation")


def test_retrieved_only_never_applied_and_actual_action_gate_output_required(pilot):
    f, w, e, _, document, *_ = pilot
    first = execute(f, w.id, document, f.selected([e.id]), 1000)
    assert first.data["records"] == []
    activate_rule(pilot)
    result = execute(f, w.id, document, f.selected([e.id]), 1000)
    record = result.data["records"][0]
    assert record["verdict"] == "APPLIED_VERIFIED"
    assert [event["kind"] for event in record["events"]] == ["SELECTED", "ACTION", "GATE"]
    assert record["events"][1]["output_hash"] == record["events"][2]["output_hash"]
    assert record["activation_id"] in result.depends_on and document.id in result.depends_on
    assert "직접 실험" not in str(result.data)


def test_not_triggered_is_not_applied_and_failure_blocks_instead_of_fabricating(pilot):
    f, w, e, _, document, *_ = pilot
    activate_rule(pilot)
    document.data = {**document.data, "text": "실험을 설계했습니다.", "claims": []}
    assert execute(f, w.id, document, f.selected([e.id]), 1000).data["records"][0]["verdict"] == "SELECTED_NOT_TRIGGERED"
    document.data = {**document.data, "text": "성과 999%", "claims": []}
    bad = execute(f, w.id, document, f.selected([e.id]), 1000)
    assert bad.data["records"][0]["verdict"] == "BLOCKED_BY_POLICY"
    assert bad.data["issues"][0]["code"] == "UNSUPPORTED_METRIC"


@pytest.mark.parametrize("change", ["source", "index", "contract", "code"])
def test_source_contract_index_and_implementation_changes_hold_existing_activation(pilot, change, monkeypatch):
    f, w, e, _, document, index, source, contracts, contract = pilot
    activate_rule(pilot)
    execute(f, w.id, document, f.selected([e.id]), 1000)
    if change == "source":
        source.write_text("changed source", encoding="utf-8")
    elif change == "index":
        write_index(index, [index_row(original_rule_summary="후속 해석이 달라짐")])
    elif change == "contract":
        contract["version"] = 2
        contracts.write_text(json.dumps({"contracts": [contract]}), encoding="utf-8")
    else:
        monkeypatch.setattr("career.rule_pilot.implementation_hash", lambda: "f" * 64)
    with pytest.raises(ValueError):
        require_checks(f, w.id, document)
    result = execute(f, w.id, document, f.selected([e.id]), 1000)
    assert result.data["records"][0]["verdict"] == "BLOCKED_BY_POLICY"


def test_missing_catalog_cannot_silently_drop_active_rule_and_retirement_is_explicit(pilot, monkeypatch):
    f, w, e, _, document, *_ = pilot
    activate_rule(pilot)
    monkeypatch.setenv("CAREER_RULE_INDEX_PATH", "unavailable-private-marker.csv")
    state = snapshot(f, w.id)
    assert state["availability"] == "UNAVAILABLE" and "unavailable-private-marker" not in str(state)
    result = execute(f, w.id, document, f.selected([e.id]), 1000)
    assert result.data["records"][0]["verdict"] == "BLOCKED_BY_POLICY"
    retire(f, w.id, request(f, w), "retire-unavailable")
    assert not adopted(f, w.id)


def test_existing_review_lock_checks_preserved_trace_current_and_feature_off_cannot_bypass(pilot, monkeypatch):
    f, w, _, q, document, *_ = pilot
    activate_rule(pilot)
    review = f.review(w.id, q["id"], manual_verified=True)
    execution = f.artifact(w.id, "RuleExecution", q["id"])
    assert execution.id in review.depends_on and review.data["rule_execution_id"] == execution.id
    f.final_lock(w.id, q["id"])
    require_checks(f, w.id, document)  # Locking status alone must not change input proof.
    monkeypatch.setenv("CAREER_RULE_PILOT_ENABLED", "0")
    with pytest.raises(ValueError, match="다시 켜고"):
        require_checks(f, w.id, document)


def test_isolation_stale_request_idempotency_and_source_traversal(pilot):
    f, w, _, _, _, _, _, contracts, contract = pilot
    old = request(f, w)
    first = review_source(f, w.id, old, "stable-review-key")
    assert review_source(f, w.id, old, "stable-review-key").id == first.id
    with pytest.raises(ValueError):
        review_source(f, w.id, old, "old-revision")
    with pytest.raises(LookupError):
        snapshot(Workflow(f.db, "someone-else"), w.id)
    before = list(f.db.scalars(select(Artifact.id)))
    contract["source_file"] = "../private-marker.txt"
    contracts.write_text(json.dumps({"contracts": [contract]}), encoding="utf-8")
    assert snapshot(f, w.id)["rules"][0]["proof"] is None
    with pytest.raises(ValueError):
        activate(f, w.id, request(f, w), "traversal-activation")
    assert before == list(f.db.scalars(select(Artifact.id)))


def test_empty_and_duplicate_or_malformed_index_and_unbounded_contract_fail_closed(pilot):
    _, _, _, _, _, index, _, contracts, contract = pilot
    write_index(index, [index_row(), index_row()])
    assert catalog()[2] == "UNAVAILABLE"
    write_index(index, [index_row()])
    contract["action"] = "RUN_ARBITRARY_CODE"
    contracts.write_text(json.dumps({"contracts": [contract]}), encoding="utf-8")
    assert catalog()[2] == "UNAVAILABLE"


@pytest.mark.parametrize("action,gate", [("CHECK_LENGTH", "CURRENT_LENGTH"), ("CHECK_OWNERSHIP", "SCOPED_OWNERSHIP")])
def test_other_bounded_handlers_run_real_positive_and_negative_cases(pilot, action, gate):
    f, w, _, _, _, _, source, contracts, contract = pilot
    statement = "현재 분량 제한을 검사합니다." if action == "CHECK_LENGTH" else "본인의 실제 수행 범위 안에서만 씁니다."
    source.write_text("# Synthetic rule\n" + statement + "\n", encoding="utf-8")
    contract.update(source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(), excerpt_sha256=hashlib.sha256(statement.encode()).hexdigest(),
                    action=action, gate=gate, trigger="ALWAYS")
    if action == "CHECK_LENGTH":
        contract["cases"][1].update(document={"text": "내용" * 20, "claims": []}, limit=10, expected_codes=["CHAR_LIMIT"])
    else:
        negative = contract["cases"][1]
        cited = negative["evidence"][0]
        cited["data"]["ownership"] = {"implementation": "TEAM"}
        negative.update(document={"text": "혼자 개발했습니다.", "claims": [{"text": "혼자 개발했습니다.", "type": "OWNERSHIP",
            "evidence_ids": [cited["id"]], "support": "SUPPORTED", "ownership_ok": True}]}, expected_codes=["OWNERSHIP"])
    contracts.write_text(json.dumps({"contracts": [contract]}), encoding="utf-8")
    review_source(f, w.id, request(f, w), "other-review")
    evaluated = evaluate(f, w.id, request(f, w), "other-evaluation")
    assert evaluated.data["status"] == "PASSED", evaluated.data
