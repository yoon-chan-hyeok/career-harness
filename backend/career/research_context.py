"""Describe research limitations without turning missing information into facts."""

from career.schemas import ResearchResult


def scope(result: ResearchResult, mode: str) -> dict:
    source_ids = {source.id for source in result.sources}
    facts = result.official_facts + result.external_evidence
    missing = []
    if not any(fact.freshness == "CURRENT" and fact.source_id in source_ids for fact in facts):
        missing.append("현재 확인된 회사·사업·조직 자료")
    if not result.role_signals:
        missing.append("조직·직무의 실제 업무 자료")
    if not any(signal.source_id in source_ids for signal in result.historical_jd_signals):
        missing.append("출처가 연결된 과거·경력·유사 공고")
    if not any(inference.supporting_source_ids for inference in result.inferences):
        missing.append("공개 근거에 연결된 채용 배경 가설(Why Now)")
    jd_only = not result.sources
    return {
        "basis": "JD_ONLY" if jd_only else "SOURCE_BACKED_PARTIAL",
        "summary": (
            "실시간 조사를 완료하지 못해 등록한 공고만으로 진행합니다. 회사·조직과 채용 배경은 확인이 필요합니다."
            if jd_only and mode == "LIVE_UNAVAILABLE_MANUAL_FALLBACK"
            else "등록한 공고만으로 진행합니다. 회사·조직과 채용 배경은 확인이 필요합니다."
            if jd_only
            else "등록한 출처를 바탕으로 분석합니다. 출처의 시점과 빠진 자료를 확인해 주세요."
        ),
        "missing_information": missing,
        "research_complete": False,
        "why_now_confirmed": False,
    }
