import re
from typing import Any

from career.quantities import numeric_token, numeric_tokens

GOOD = {"VERIFIED", "USER_CONFIRMED", "SOURCE_BACKED"}


def ledger_coverage(document):
    """Every prose span needs a ledger entry; coverage is not semantic proof."""
    remaining = document["text"]
    for claim in document.get("claims", []):
        quote = claim.get("text", "")
        if quote:
            remaining = remaining.replace(quote, " " * len(quote))
    remaining = re.sub(r"(?m)^\s*#{1,6}\s+[^\n]*$", "", remaining)
    if re.search(r"[\w가-힣]", remaining):
        return [
            {
                "code": "LEDGER_COVERAGE",
                "priority": "P0",
                "message": "본문에 주장 근거가 연결되지 않은 문장이 있습니다. 전체 본문의 사실·해석을 ClaimLedger로 확인해 주세요.",
            }
        ]
    return []


def hard_qa(
    text: str,
    evidence: list[dict[str, Any]],
    limit: int = 10000,
    *,
    profile=None,
    company_facts=None,
    document=None,
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []

    def issue(code: str, message: str):
        issues.append({"code": code, "priority": "P0" if code != "CHAR_LIMIT" else "P1", "message": message})

    if len(text) > limit:
        issue("CHAR_LIMIT", f"{len(text)} / {limit}자: 분량을 줄여 주세요.")
    if not text.strip():
        issue("EMPTY", "문서가 비어 있습니다.")
    profile = profile or {}
    exact_profile_quotes = [
        f["value"].get("text", "")
        for f in profile.values()
        if f.get("fact_type") == "profile"
        and f.get("status") in GOOD
        and f.get("source_id")
        and isinstance(f.get("value"), dict)
        and isinstance(f["value"].get("text"), str)
        and f["value"].get("text", "").strip()
        and f["value"]["text"] in text
    ]
    if not evidence and not exact_profile_quotes:
        issue("NO_EVIDENCE", "선택한 검증 근거가 없습니다.")
    valid = [e for e in evidence if e.get("status") in GOOD and e.get("source_id")]
    for e in evidence:
        if e.get("status") not in GOOD:
            issue("STALE_SOURCE", "미확인·충돌·삭제된 근거를 사용할 수 없습니다.")
        if not e.get("source_id"):
            issue("MISSING_SOURCE", "출처가 없습니다.")
        data = e.get("data", {})
        for boundary in data.get("forbidden_claims", []) + data.get("claim_boundaries", []):
            if boundary and boundary in text:
                issue("CLAIM_BOUNDARY", f"사용 금지 주장: {boundary}")
        ownership = data.get("ownership")
        implementation = (
            ownership.get("implementation", "UNKNOWN") if isinstance(ownership, dict) else "UNKNOWN"
        )
        if document is None and implementation != "USER":
            if any(
                phrase in text
                for phrase in ["혼자 개발", "전부 직접 구현", "단독 개발", "built entirely myself"]
            ):
                issue("OWNERSHIP", "선택한 근거가 단독 구현 주장을 뒷받침하지 않습니다.")
    if document is not None:
        from career.document_qa import ownership_issues

        issues.extend(ownership_issues(document, evidence))
    # Exact numbers are necessary, but semantic scope is reviewed separately.
    supported = numeric_tokens("\n".join(e["body"] for e in valid))
    for e in valid:
        for metric in e.get("data", {}).get("metric_ledger", []):
            if metric.get("status") in GOOD:
                supported.update(numeric_tokens(str(metric["value"]) + str(metric.get("unit", ""))))
    # A graduation date is valid only in its exact canonical profile quote;
    # the same number elsewhere still needs independent metric evidence.
    metric_text = text
    for quote in exact_profile_quotes:
        metric_text = metric_text.replace(quote, "")
    for fact in company_facts or []:
        if fact.get("freshness") == "CURRENT" and fact.get("source_id") and fact.get("statement"):
            metric_text = metric_text.replace(fact["statement"], "")
    for number in numeric_tokens(metric_text) - supported:
        issue("UNSUPPORTED_METRIC", f"근거에 없는 숫자: {number}")
    # An old raw source cannot keep a superseded metric valid after correction.
    for e in valid:
        ledger = e.get("data", {}).get("metric_ledger", [])
        current_values = {numeric_token(str(m["value"])) for m in ledger if m.get("status") in GOOD}
        for metric in ledger:
            value = str(metric.get("value", ""))
            literal = bool(re.fullmatch(r"\d+(?:[.,]\d+)*(?:%|배)?", value))
            appears = (
                (numeric_token(value).rstrip("%배") in {n.rstrip("%배") for n in numeric_tokens(text)})
                if literal
                else bool(value and re.search(r"(?<!\d)" + re.escape(value) + r"(?!\d)", text))
            )
            if (
                metric.get("status") not in GOOD
                and value
                and appears
                and numeric_token(value) not in current_values
            ):
                issue("METRIC_CONFLICT", "확인되지 않았거나 정정된 이전 지표입니다: " + value)
            if metric.get("status") in GOOD:
                for forbidden in metric.get("invalid_for_claims", []):
                    if forbidden and forbidden in text:
                        issue("METRIC_SCOPE", "지표의 사용 범위를 벗어납니다: " + forbidden)
    return issues
