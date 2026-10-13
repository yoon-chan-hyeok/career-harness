import re
import unicodedata
from difflib import SequenceMatcher

from career.quantities import canonical_quantity, quantities, quantity_role
from career.validation import GOOD


def _key(text):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", text).casefold())


def _label(document, index):
    return document.get("document_label") or f"문서 {index + 1}"


def _skeleton(text, values):
    text = unicodedata.normalize("NFKC", text)
    for item in reversed(values):
        text = text[: item.start] + "수치" + item.key[1] + text[item.end :]
    return _key(text)


_SOLE = re.compile(
    r"(?:혼자(?:서)?|단독(?:으로)?|전부\s*직접|독자적으로)\s*"
    r"(?:(?:전체|모든|직접|처음부터)\s*)?(?:(?:시스템|코드|프로젝트|기능)(?:을|를)?\s*)?(?:개발|구현|구축)|"
    r"(?:전체|모든)\s*(?:시스템|코드|기능)(?:을|를)?\s*직접\s*(?:개발|구현|구축)|built entirely myself",
    re.I,
)
_ASSISTED = re.compile(
    r"(?:Codex|GPT|AI)(?:의)?\s*(?:도움|보조|지원)(?:을|를)?\s*(?:받아|받아서)?\s*(?:개발|구현|구축)|(?:Codex|GPT)(?:로|를 활용해)\s*(?:구현|개발)",
    re.I,
)
_NEGATION = re.compile(
    r"^(?:하(?:지\s*(?:않|못)|고\s*싶|려)|한\s*(?:것[이은]?|적[이는은]?)?\s*(?:아니|아닙|아님|없)|할\s*(?:수|계획|예정))"
)


def _asserted(pattern, text):
    for match in pattern.finditer(text):
        if not _NEGATION.match(text[match.end() :].lstrip()):
            return True
    return False


def ownership_issues(document, evidence):
    """Apply implementation ownership only to the claim's cited evidence."""
    rows = {item["id"]: item for item in evidence}
    result = []
    for claim in document.get("claims", []):
        if not _asserted(_SOLE, claim["text"]):
            continue
        chosen = [rows[e] for e in claim.get("evidence_ids", []) if e in rows]
        values = set()
        for item in chosen:
            ownership = item.get("data", {}).get("ownership", {})
            values.add(
                ownership.get("implementation", "UNKNOWN") if isinstance(ownership, dict) else "UNKNOWN"
            )
        if not chosen or values == {"USER"}:
            continue
        ambiguous = len(chosen) > 1 and "USER" in values
        result.append(
            {
                "code": "OWNERSHIP",
                "priority": "P2" if ambiguous else "P0",
                "message": (
                    "여러 경험의 수행 범위가 한 문장에 섞였습니다. 주장과 근거를 문장별로 구분해 주세요: "
                    if ambiguous
                    else "선택한 경험의 구현 범위가 단독·전체 구현 주장을 뒷받침하지 않습니다: "
                )
                + claim["text"],
            }
        )
    return result


def cross_document_qa(documents: list[dict], evidence=None):
    issues = []
    seen_issues = set()
    metrics = {}
    for item in evidence or []:
        if item.get("status") not in GOOD or not item.get("source_id"):
            continue
        for metric in item.get("data", {}).get("metric_ledger", []):
            if metric.get("status") in GOOD and metric.get("id"):
                metrics[metric["id"]] = (item["id"], metric)

    def add(code, priority, message, identity):
        marker = (code, identity)
        if marker not in seen_issues:
            seen_issues.add(marker)
            issues.append({"code": code, "priority": priority, "message": message})

    metric_seen, fact_seen, ownership_seen = {}, {}, {}
    for index, document in enumerate(documents):
        label = _label(document, index)
        for claim in document.get("claims", []):
            text = claim["text"]
            values = quantities(text, ignore_identifiers=True)
            ids = tuple(sorted(set(claim.get("evidence_ids", []))))
            metric_ids = tuple(sorted(set(claim.get("metric_ids", []))))
            for metric_id in metric_ids:
                canonical = metrics.get(metric_id)
                selected = values
                expected = baseline = None
                if canonical:
                    evidence_id, metric = canonical
                    if evidence_id not in ids:
                        add(
                            "CROSS_DOCUMENT_METRIC_SCOPE",
                            "P1",
                            f"{label}: 지표와 연결한 경험이 다릅니다. 현재 지표의 출처를 확인해 주세요.",
                            (index, metric_id),
                        )
                        continue
                    expected = canonical_quantity(str(metric["value"]), metric.get("unit", ""))
                    baseline = canonical_quantity(str(metric.get("baseline") or ""), metric.get("unit", ""))
                    if expected is None or expected.key[1] not in {
                        "",
                        "%",
                        "pp",
                        "seconds",
                        "bytes",
                        "점",
                        "명",
                        "개",
                        "건",
                        "회",
                        "일",
                        "개월",
                        "년",
                        "배",
                    }:
                        add(
                            "METRIC_ASSOCIATION_REVIEW",
                            "P2",
                            f"{label}: 범위·복합 값 또는 단위 해석이 필요한 지표입니다. 원문과 각 문장의 수치를 직접 대조해 주세요: {text}",
                            (index, metric_id),
                        )
                        continue
                    if expected:
                        selected = [v for v in values if v.key[1] == expected.key[1]]
                        if not selected and len(values) == 1 and len(metric_ids) == 1:
                            add(
                                "CROSS_DOCUMENT_METRIC_UNIT",
                                "P1",
                                f"{label}: {metric['name']}의 단위가 현재 확인한 지표와 다릅니다. 문장: {text}",
                                (index, metric_id),
                            )
                            continue
                # Multiple same-unit metrics in one claim have no numeric-to-ID map.
                same_unit_ids = [
                    m
                    for m in metric_ids
                    if m in metrics
                    and expected
                    and (q := canonical_quantity(str(metrics[m][1]["value"]), metrics[m][1].get("unit", "")))
                    and q.key[1] == expected.key[1]
                ]
                if len(selected) > 1 or len(same_unit_ids) > 1:
                    if (
                        expected
                        and baseline
                        and len(same_unit_ids) == 1
                        and {quantity_role(text, v) for v in selected} == {"baseline", "value"}
                    ):
                        pass
                    else:
                        add(
                            "METRIC_ASSOCIATION_REVIEW",
                            "P2",
                            f"{label}: 여러 수치와 지표가 한 주장에 연결됐습니다. 기준값·결과값과 지표별 원문을 구분해 주세요: {text}",
                            (index, metric_id),
                        )
                        continue
                if not selected:
                    continue
                for value in selected:
                    role = quantity_role(text, value)
                    if expected:
                        if role == "baseline" and baseline is None:
                            add(
                                "METRIC_ASSOCIATION_REVIEW",
                                "P2",
                                f"{label}: 기준값이 현재 지표 장부에 없어 원문 대조가 필요합니다: {text}",
                                (index, metric_id, "baseline"),
                            )
                            continue
                        allowed = (
                            baseline.key == value.key
                            if role == "baseline" and baseline
                            else expected.key == value.key
                        )
                        if not allowed:
                            add(
                                "CROSS_DOCUMENT_METRIC_VALUE",
                                "P1",
                                f"{label}: {metric['name']}의 수치가 현재 확인한 지표와 다릅니다. 문장: {text}",
                                (index, metric_id),
                            )
                    identity = (metric_id, role)
                    previous = metric_seen.setdefault(identity, [])
                    for old_index, old_label, old_value in previous:
                        if old_index != index and old_value != value.key:
                            add(
                                "CROSS_DOCUMENT_METRIC",
                                "P1",
                                f"{old_label} / {label}: 같은 지표의 {('기준값' if role == 'baseline' else '결과값')}을 다르게 썼습니다. 원자료 범위를 확인해 주세요.",
                                (metric_id, role, old_index, index),
                            )
                    previous.append((index, label, value.key))
            uncertain_metric = any(
                m in metrics
                and canonical_quantity(str(metrics[m][1]["value"]), metrics[m][1].get("unit", "")) is None
                for m in metric_ids
            )
            if (
                ids
                and len(values) == 1
                and len(metric_ids) <= 1
                and not uncertain_metric
                and claim.get("type") in {"FACT", "METRIC"}
            ):
                signature = (ids, metric_ids, _skeleton(text, values))
                previous = fact_seen.setdefault(signature, [])
                for old_index, old_label, old_values in previous:
                    current = tuple(v.key for v in values)
                    if old_index != index and current != old_values:
                        add(
                            "CROSS_DOCUMENT_FACT_NUMBER",
                            "P1",
                            f"{old_label} / {label}: 같은 근거·같은 사실 문장의 수치를 다르게 썼습니다. 문장: {text}",
                            (signature, old_index, index),
                        )
                previous.append((index, label, tuple(v.key for v in values)))
            if len(ids) == 1:
                implementation = (
                    "SOLE" if _asserted(_SOLE, text) else "ASSISTED" if _asserted(_ASSISTED, text) else None
                )
                if implementation:
                    previous = ownership_seen.setdefault(ids[0], [])
                    for old_index, old_label, old_value in previous:
                        if old_index != index and old_value != implementation:
                            add(
                                "CROSS_DOCUMENT_OWNERSHIP",
                                "P1",
                                f"{old_label} / {label}: 같은 경험의 구현을 한 문서에서는 단독 전체 수행, 다른 문서에서는 AI 보조 수행으로 썼습니다. 실제 수행 범위를 확인해 주세요.",
                                (ids[0], old_index, index),
                            )
                    previous.append((index, label, implementation))
        if evidence:
            for issue in ownership_issues(document, evidence):
                add(
                    issue["code"],
                    issue["priority"],
                    label + ": " + issue["message"],
                    (index, issue["message"]),
                )
    return issues


def portfolio_qa(briefs: list[dict], documents: list[dict], *, strict_repetition=False):
    issues = []
    messages = [_key(b["primary_message"]) for b in briefs]
    if len(messages) != len(set(messages)):
        issues.append(
            {"code": "DUPLICATE_MESSAGE", "priority": "P1", "message": "문항 간 핵심 메시지가 중복됩니다."}
        )
    for i, message in enumerate(messages):
        for other in messages[i + 1 :]:
            if message != other and SequenceMatcher(None, message, other).ratio() > 0.86:
                issues.append(
                    {
                        "code": "SIMILAR_MESSAGE",
                        "priority": "P2",
                        "message": "문항별 핵심 메시지가 매우 비슷합니다. 각 문항의 판단·역할을 구분하세요.",
                    }
                )
    for i, document in enumerate(documents):
        metrics = {q.key for q in quantities(document["text"], ignore_identifiers=True)}
        for j, other in enumerate(documents[i + 1 :], i + 1):
            shared = metrics.intersection(q.key for q in quantities(other["text"], ignore_identifiers=True))
            if shared:
                issues.append(
                    {
                        "code": "REPEATED_METRIC",
                        "priority": "P2",
                        "message": f"{_label(document, i)} / {_label(other, j)}: 같은 수치 표현이 반복됩니다. 문항별 다른 사실·판단을 보여 주세요.",
                    }
                )
            first = _fact_statements(document)
            second = _fact_statements(other)
            for identity in first.keys() & second.keys():
                issues.append(
                    {
                        "code": "REPEATED_FACT",
                        "priority": "P1" if strict_repetition else "P2",
                        "message": f"{_label(document, i)} / {_label(other, j)}: 같은 근거의 사실 문장을 반복했습니다: {first[identity]}",
                    }
                )
            # Confirmed metric identity is stronger than a coincidental repeated numeral.
            first_ids = {m for c in document.get("claims", []) for m in c.get("metric_ids", [])}
            second_ids = {m for c in other.get("claims", []) for m in c.get("metric_ids", [])}
            if first_ids & second_ids:
                issues.append(
                    {
                        "code": "REPEATED_METRIC_ID",
                        "priority": "P1" if strict_repetition else "P2",
                        "message": f"{_label(document, i)} / {_label(other, j)}: 같은 지표를 여러 문항의 성과로 반복했습니다. 문항별 다른 근거를 사용해 주세요.",
                    }
                )
    types = {b.get("question_type") for b in briefs}
    if len(briefs) > 2 and types == {"JOB_COMPETENCY"}:
        issues.append(
            {
                "code": "PORTFOLIO_BALANCE",
                "priority": "P2",
                "message": "질문이 허용하면 협업·가치관·본업 선택 이유도 배분해 주세요.",
            }
        )
    return issues


def _fact_statements(document):
    result = {}
    for claim in document.get("claims", []):
        ids = tuple(sorted(set(claim.get("evidence_ids", []))))
        if not ids or claim.get("profile_fact_ids") or claim.get("company_source_ids"):
            continue
        if claim.get("type") not in {"FACT", "METRIC", "OWNERSHIP"}:
            continue
        for sentence in re.split(r"(?<!\d)[.!?]|[.!?](?!\d)|\n+", claim["text"]):
            key = _key(sentence)
            if len(key) >= 12:
                result[(ids, key)] = sentence.strip()
    return result


def skimmability_qa(text: str):
    issues = []
    for line in text.splitlines():
        bullet = line.strip().lstrip("-*• ").strip()
        if re.match(r"^(Python|SQL|Java|PyTorch|TensorFlow|React|Kafka)(?:\s*[,/·+]|\s+사용)", bullet, re.I):
            issues.append(
                {
                    "code": "TOOL_FIRST",
                    "priority": "P2",
                    "message": "기술 목록보다 만든 산출물·결과를 먼저 보여 주세요: " + bullet[:70],
                }
            )
        if len(bullet) > 220:
            issues.append(
                {
                    "code": "LONG_BULLET",
                    "priority": "P2",
                    "message": "한 항목을 독립적으로 이해할 수 있게 줄여 주세요.",
                }
            )
        if bullet.startswith(("이를 통해", "이러한", "위의")):
            issues.append(
                {
                    "code": "DEPENDENT_BULLET",
                    "priority": "P2",
                    "message": "앞 문장을 읽지 않아도 이해되는 항목으로 바꿔 주세요.",
                }
            )
    return issues
