from copy import deepcopy
from decimal import Decimal

import pytest
from career.document_qa import cross_document_qa, ownership_issues, portfolio_qa
from career.quantities import numeric_token, quantities
from career.validation import hard_qa


def document(text, metric_ids=None, evidence_id="e", kind="METRIC", label=""):
    return {
        "text": text,
        "document_label": label,
        "claims": [
            {
                "text": text,
                "type": kind,
                "evidence_ids": [evidence_id],
                "metric_ids": metric_ids or [],
                "support": "SUPPORTED",
                "ownership_ok": True,
            }
        ],
    }


def evidence(value="3", unit="개", baseline=None, metric_id="m", name="보고서 수", ownership="USER"):
    return {
        "id": "e",
        "source_id": "source",
        "status": "VERIFIED",
        "title": "Synthetic",
        "body": "보고서 3개와 4개를 기록했고 70%와 80%의 범위를 구분했습니다.",
        "data": {
            "ownership": {"implementation": ownership},
            "metric_ledger": [
                {
                    "id": metric_id,
                    "name": name,
                    "value": value,
                    "unit": unit,
                    "baseline": baseline,
                    "status": "VERIFIED",
                    "source_id": "source",
                }
            ],
        },
    }


def codes(issues):
    return {i["code"] for i in issues}


@pytest.mark.parametrize(
    "first,second", [("3개", "4개"), ("1,000건", "900건"), ("1.25초", "1.3초"), ("8명", "9명")]
)
def test_same_metric_conflict_includes_counts_decimals_times_and_people(first, second):
    issues = cross_document_qa([document("결과 " + first, ["m"]), document("결과 " + second, ["m"])])
    assert "CROSS_DOCUMENT_METRIC" in codes(issues)
    assert any(i["priority"] == "P1" for i in issues)


@pytest.mark.parametrize(
    "first,second",
    [
        ("1,000건", "1000.0건"),
        ("1초", "1000ms"),
        ("2분", "120초"),
        ("8명", "8 people"),
        ("80%", "80 percent"),
    ],
)
def test_equivalent_numeric_formatting_and_explicit_units_are_not_conflicts(first, second):
    assert cross_document_qa([document("결과 " + first, ["m"]), document("결과 " + second, ["m"])]) == []


def test_same_metric_baseline_and_result_are_separate_roles():
    rows = [evidence("80", "%", "70", name="정확도")]
    docs = [
        document("기존 정확도 70%에서 정확도 80%로 바꿨습니다.", ["m"]),
        document("정확도 80%를 확인했습니다.", ["m"]),
    ]
    assert not cross_document_qa(docs, rows)
    assert not cross_document_qa([document("기존 정확도 70%", ["m"]), document("정확도 80%", ["m"])], rows)
    wrong = cross_document_qa([document("정확도 70%를 달성했습니다.", ["m"])], rows)
    assert "CROSS_DOCUMENT_METRIC_VALUE" in codes(wrong)
    wrong_baseline = cross_document_qa(
        [document("기존 정확도 80%에서 정확도 80%로 바꿨습니다.", ["m"])], rows
    )
    assert "CROSS_DOCUMENT_METRIC_VALUE" in codes(wrong_baseline)
    assert not cross_document_qa([document("Accuracy improved from 70% to 80%.", ["m"])], rows)


@pytest.mark.parametrize("unit,phrase", [("개월", "기간 12개월"), ("점", "Result 12 scores")])
def test_longer_units_and_english_score_do_not_become_prefix_units(unit, phrase):
    assert not cross_document_qa([document(phrase, ["m"])], [evidence("12", unit)])


def test_metric_name_scope_and_unit_use_current_confirmed_ledger():
    rows = [evidence()]
    assert "CROSS_DOCUMENT_METRIC_VALUE" in codes(cross_document_qa([document("보고서 4개", ["m"])], rows))
    assert "CROSS_DOCUMENT_METRIC_UNIT" in codes(cross_document_qa([document("보고서 3명", ["m"])], rows))
    assert "CROSS_DOCUMENT_METRIC_SCOPE" in codes(
        cross_document_qa([document("보고서 3개", ["m"], evidence_id="other")], rows)
    )
    rows[0]["data"]["metric_ledger"][0]["status"] = "SUPERSEDED"
    assert not cross_document_qa([document("보고서 4개", ["m"])], rows)


def test_different_metric_id_and_dataset_dont_share_numeric_identity():
    first = evidence("80", "%", metric_id="first", name="Subset A")
    second = evidence("90", "%", metric_id="second", name="Subset B")
    first["data"]["metric_ledger"] += second["data"]["metric_ledger"]
    assert not cross_document_qa(
        [document("정확도 80%", ["first"]), document("정확도 90%", ["second"])], [first]
    )


def test_ambiguous_multiple_metrics_and_range_values_require_clarification_not_false_contradiction():
    rows = evidence("80", "%", metric_id="a")
    rows["data"]["metric_ledger"] += evidence("90", "%", metric_id="b")["data"]["metric_ledger"]
    issues = cross_document_qa([document("두 지표는 80%와 90%였습니다.", ["a", "b"])], [rows])
    assert codes(issues) == {"METRIC_ASSOCIATION_REVIEW"} and all(i["priority"] == "P2" for i in issues)
    ranged = evidence("3~4", "개")
    issues = cross_document_qa([document("보고서 3개", ["m"]), document("보고서 4개", ["m"])], [ranged])
    assert codes(issues) == {"METRIC_ASSOCIATION_REVIEW"}


def test_same_fact_integer_difference_without_metric_id_is_detected_with_labels():
    issues = cross_document_qa(
        [
            document("검증 보고서 3개를 작성했습니다.", label="자소서 1번", kind="FACT"),
            document("검증 보고서 4개를 작성했습니다.", label="레쥬메", kind="FACT"),
        ]
    )
    assert codes(issues) == {"CROSS_DOCUMENT_FACT_NUMBER"}
    assert "자소서 1번 / 레쥬메" in issues[0]["message"]
    assert not cross_document_qa(
        [document("회의를 3회 운영했습니다."), document("보고서 4개를 작성했습니다.")]
    )


def test_implementation_ownership_conflict_is_scoped_and_has_no_negation_bypass():
    docs = [
        document("전체 코드를 직접 구현했습니다.", kind="OWNERSHIP"),
        document("Codex 도움을 받아 구현했습니다.", kind="OWNERSHIP"),
    ]
    assert "CROSS_DOCUMENT_OWNERSHIP" in codes(cross_document_qa(docs))
    assert "OWNERSHIP" in codes(cross_document_qa([docs[0]], [evidence(ownership="USER_AI_ASSISTED")]))
    assert not ownership_issues(
        document("전체 코드를 직접 구현한 것이 아닙니다."), [evidence(ownership="TEAM")]
    )
    assert not ownership_issues(
        document("단독으로 문제를 정의하고 도구를 수정했습니다."), [evidence(ownership="TEAM")]
    )
    bad = document("전체 코드를 직접 구현했지만 배포하지 않았습니다.")
    assert ownership_issues(bad, [evidence(ownership="USER_AI_ASSISTED")])
    other = evidence(ownership="TEAM")
    other["id"] = "other"
    assert not ownership_issues(document("전체 코드를 직접 구현했습니다."), [evidence(), other])


def test_document_aware_hard_qa_does_not_apply_other_projects_ownership_to_a_claim():
    other = evidence(ownership="TEAM")
    other["id"] = "other"
    doc = document("전체 코드를 직접 구현했습니다.")
    assert not hard_qa(doc["text"], [evidence(), other], document=doc)
    doc["claims"][0]["evidence_ids"] = ["other"]
    assert "OWNERSHIP" in codes(hard_qa(doc["text"], [evidence(), other], document=doc))


def test_portfolio_same_project_different_facts_and_roles_are_allowed():
    docs = [
        document("검증 실험의 기준을 재설계했습니다.", kind="FACT"),
        document("동료와 역할을 나누고 결과를 조율했습니다.", kind="FACT"),
    ]
    assert not portfolio_qa(
        [{"primary_message": "실험 설계"}, {"primary_message": "팀 조율"}], docs, strict_repetition=True
    )


def test_general_numeric_repetition_and_same_fact_have_distinct_confidence():
    docs = [
        document("검증 보고서 3개를 작성했습니다.", kind="FACT"),
        document("검증 보고서 3.0개를 작성했습니다.", kind="FACT"),
    ]
    issues = portfolio_qa([], docs, strict_repetition=True)
    assert "REPEATED_METRIC" in codes(issues)
    exact = [document("검증 보고서를 작성하고 결과를 확인했습니다.", kind="FACT")] * 2
    strict = portfolio_qa([], exact, strict_repetition=True)
    assert next(i for i in strict if i["code"] == "REPEATED_FACT")["priority"] == "P1"
    warning = portfolio_qa([], exact)
    assert next(i for i in warning if i["code"] == "REPEATED_FACT")["priority"] == "P2"
    metrics = portfolio_qa(
        [], [document("성능 80%", ["m"]), document("성능을 80% 확인", ["m"])], strict_repetition=True
    )
    assert next(i for i in metrics if i["code"] == "REPEATED_METRIC_ID")["priority"] == "P1"


def test_dates_and_software_versions_do_not_become_repeated_achievement_numbers():
    assert not portfolio_qa([], [{"text": "2026-09-29에 Python 3.12와 GPT-4.1을 사용"}] * 2)
    assert quantities("value 3개", ignore_identifiers=True)[0].value == Decimal(3)
    assert quantities("Python으로 3회 평가", ignore_identifiers=True)[0].value == Decimal(3)


def test_spacing_and_punctuation_cannot_hide_duplicate_messages():
    issues = portfolio_qa(
        [{"primary_message": "실험을 검증했습니다."}, {"primary_message": "실험을  검증했습니다!"}], []
    )
    assert codes(issues) == {"DUPLICATE_MESSAGE"}


def test_normalized_numbers_do_not_expand_support_or_hide_superseded_values():
    row = evidence("1000", "건")
    row["body"] = "1,000건을 확인했습니다."
    assert not hard_qa("1000.0건을 확인했습니다.", [row])
    assert "UNSUPPORTED_METRIC" in codes(hard_qa("1001건을 확인했습니다.", [row]))
    assert numeric_token("1,00") == "1,00"
    row["data"]["metric_ledger"][0]["status"] = "SUPERSEDED"
    assert "METRIC_CONFLICT" in codes(hard_qa("1,000건을 확인했습니다.", [row]))
    current = deepcopy(row["data"]["metric_ledger"][0])
    current.update(value="1000.0", status="VERIFIED")
    row["data"]["metric_ledger"].append(current)
    assert not hard_qa("1,000건을 확인했습니다.", [row])


def test_large_integer_values_and_percent_spacing_are_exact():
    first = "123456789012345678901234567891"
    second = "123456789012345678901234567892"
    assert numeric_token(first) != numeric_token(second)
    assert "CROSS_DOCUMENT_METRIC" in codes(
        cross_document_qa([document(first + "건", ["m"]), document(second + "건", ["m"])])
    )
    row = evidence("80", "%")
    assert not hard_qa("80 %를 확인했습니다.", [row])
