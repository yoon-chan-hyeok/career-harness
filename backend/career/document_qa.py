import re
from difflib import SequenceMatcher


def cross_document_qa(documents: list[dict]):
    issues = []
    metric_values: dict[str, set[str]] = {}
    for document in documents:
        for claim in document.get("claims", []):
            for metric in claim.get("metric_ids", []):
                values = set(re.findall(r"\d+(?:\.\d+)?%", claim["text"]))
                previous = metric_values.setdefault(metric, values)
                if values and previous and values != previous:
                    issues.append(
                        {
                            "code": "CROSS_DOCUMENT_METRIC",
                            "priority": "P1",
                            "message": "같은 지표를 문서마다 다른 값으로 사용했습니다. 원자료 범위를 확인하세요.",
                        }
                    )
    return issues


def portfolio_qa(briefs: list[dict], documents: list[dict]):
    issues = []
    messages = [b["primary_message"].strip() for b in briefs]
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
        metrics = set(re.findall(r"\d+(?:\.\d+)?%", document["text"]))
        for other in documents[i + 1 :]:
            if metrics.intersection(re.findall(r"\d+(?:\.\d+)?%", other["text"])):
                issues.append(
                    {
                        "code": "REPEATED_METRIC",
                        "priority": "P2",
                        "message": "같은 수치가 반복됩니다. 문항별 다른 판단을 보여 주세요.",
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
