from career.validation import ledger_coverage


def test_hidden_non_numeric_prose_is_not_covered_by_one_supported_sentence():
    assert (
        ledger_coverage(
            {
                "text": "실험을 설계했습니다.\n운영 배포까지 맡았습니다.",
                "claims": [{"text": "실험을 설계했습니다."}],
            }
        )[0]["code"]
        == "LEDGER_COVERAGE"
    )
    assert not ledger_coverage(
        {"text": "## 프로젝트\n- 실험을 설계했습니다.", "claims": [{"text": "실험을 설계했습니다."}]}
    )
