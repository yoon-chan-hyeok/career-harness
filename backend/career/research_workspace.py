"""Source collection, quoted extraction, and an explicit hiring-context decision."""

import re
from copy import deepcopy
from datetime import date
from hashlib import sha256
from typing import Literal

from pydantic import Field, StrictBool, field_validator

from career.artifacts import fresh, latest, lock, save, stale
from career.db import now, uid
from career.public_web import MAX_TEXT, fetch_page, public_url
from career.research_context import scope
from career.schemas import ResearchResult, Schema

SourceKind = Literal["CURRENT_JD", "COMPANY", "ROLE", "HISTORICAL_JD", "EXTERNAL"]
JD_ID = "USER_SUPPLIED_JD"


class SourceInput(Schema):
    research_id: str | None = None
    source_id: str | None = None
    method: Literal["URL", "PASTE"]
    url: str = Field(default="", max_length=2048)
    title: str = Field(default="", max_length=300)
    text: str = Field(default="", max_length=MAX_TEXT)
    category: SourceKind
    published_at: date | None = None
    freshness: Literal["CURRENT", "DATED", "UNKNOWN"] = "UNKNOWN"

    @field_validator("title", "text", "url")
    @classmethod
    def trim(cls, value):
        return value.strip()


class Quote(Schema):
    source_id: str = Field(min_length=1, max_length=100)
    quote: str = Field(min_length=4, max_length=4000)


class Statement(Schema):
    statement: str = Field(min_length=4, max_length=1500)
    citation: Quote


class Hypothesis(Schema):
    text: str = Field(min_length=8, max_length=2000)
    confidence: Literal["HIGH", "MEDIUM", "LOW"] = "LOW"
    citations: list[Quote] = Field(min_length=1, max_length=8)


class Extraction(Schema):
    company_facts: list[Statement] = Field(default_factory=list, max_length=30)
    role_signals: list[Statement] = Field(default_factory=list, max_length=20)
    historical_jd_signals: list[Statement] = Field(default_factory=list, max_length=20)
    selection_process_signals: list[Statement] = Field(default_factory=list, max_length=15)
    inferences: list[Hypothesis] = Field(default_factory=list, max_length=3)


class ResearchDecision(Schema):
    research_id: str
    mode: Literal["HYPOTHESIS", "INSUFFICIENT"]
    hypothesis: str = Field(default="", max_length=2000)
    confidence: Literal["HIGH", "MEDIUM", "LOW"] = "LOW"
    citations: list[Quote] = Field(default_factory=list, max_length=8)
    limitation: str = Field(min_length=8, max_length=3000)
    confirmed: StrictBool = False


def current(service, workspace, expected_id):
    service.editable(service.ws(workspace))
    research = latest(service.db, service.user, workspace, "CompanyResearchResult", required=False)
    if (research.id if research else None) != expected_id:
        raise ValueError("조사 자료 버전이 바뀌었습니다. 현재 자료를 다시 확인해 주세요.")
    if research:
        fresh(service.db, service.user, research)
    return research


def _result(data: dict) -> ResearchResult:
    return ResearchResult.model_validate({key: data[key] for key in ResearchResult.model_fields})


def _save_research(service, workspace, data, model="manual"):
    result = _result(data)
    data = {**data, **result.model_dump(), "scope": scope(result, data["mode"]), "retrieved_at": now().isoformat()}
    return save(service.db, service.user, workspace, "CompanyResearchResult", data, model=model)[0]


def collect(service, workspace, payload: dict):
    entry = SourceInput.model_validate(payload)
    research = current(service, workspace, entry.research_id)
    if entry.method == "URL":
        page = fetch_page(entry.url)
        text, url, title = page["text"], page["url"], entry.title or page["title"]
    else:
        text, title = entry.text, entry.title
        url = public_url(entry.url) if entry.url else ""
        if not title or len(text) < 20:
            raise ValueError("자료 제목과 20자 이상의 원문을 입력해 주세요.")
    # Validate before creating a default research artifact on a failed request.
    data = deepcopy(research.data) if research else None
    documents = deepcopy(data.get("source_documents", {})) if data else {}
    sources = deepcopy(data.get("sources", [])) if data else []
    if entry.source_id and entry.source_id not in documents:
        raise ValueError("수정할 자료가 현재 조사에 없습니다.")
    source_id = entry.source_id or "web-" + uid()
    if not entry.source_id and len(sources) >= 12:
        raise ValueError("자료는 최대 12개입니다. 기존 자료를 수정하거나 필요한 부분만 합쳐 주세요.")
    if sum(len(doc["text"]) for key, doc in documents.items() if key != source_id) + len(text) > 80_000:
        raise ValueError("한 지원 작업의 조사 원문은 총 8만 자까지 저장할 수 있습니다.")
    stamp = now().isoformat()
    published = entry.published_at.isoformat() if entry.published_at else None
    freshness = "DATED" if entry.category == "HISTORICAL_JD" else entry.freshness
    if entry.published_at and entry.published_at > now().date():
        raise ValueError("게시일은 오늘 또는 이전 날짜로 입력해 주세요.")
    source = {"id": source_id, "url": url, "title": title, "published_at": published, "retrieved_at": stamp}
    sources = [item for item in sources if item["id"] != source_id] + [source]
    documents[source_id] = {
        "text": text, "content_hash": sha256(text.encode()).hexdigest(), "category": entry.category,
        "freshness": freshness, "collection_method": entry.method, "declared_by": "USER",
    }
    if data is None:
        data = deepcopy(service.research(workspace).data)
    # Replacing a source cannot retain its old derived assertions or inference.
    for key in ("official_facts", "external_evidence", "historical_jd_signals"):
        data[key] = [fact for fact in data[key] if fact.get("source_id") != source_id]
    data["inferences"] = [item for item in data["inferences"] if source_id not in item["supporting_source_ids"]]
    if entry.source_id:
        data["role_signals"], data["selection_process_signals"] = [], []
    proofs = data.get("extraction_citations", {})
    if entry.source_id:
        proofs = {field: [item for item in items if (
            source_id not in {citation["source_id"] for citation in item["citations"]}
            if field == "inferences" else item["citation"]["source_id"] != source_id
        )] for field, items in proofs.items()}
    data.update(sources=sources, source_documents=documents, mode="COLLECTED_PUBLIC_SOURCES",
                extraction_status="NEEDS_EXTRACTION", why_now_proposals=[], extraction_citations=proofs)
    return _save_research(service, workspace, data)


def source_context(service, workspace, research):
    ws = service.ws(workspace)
    return {
        JD_ID: {"title": "등록한 현재 공고", "text": ws.jd_raw, "category": "CURRENT_JD",
                "url": "", "published_at": None, "freshness": "USER_SUPPLIED"},
        **{source["id"]: {**source, **research.data.get("source_documents", {})[source["id"]]}
           for source in research.data["sources"] if source["id"] in research.data.get("source_documents", {})},
    }


def validate_quote(citation: Quote, sources: dict):
    source = sources.get(citation.source_id)
    if source is None or not citation.quote.strip() or citation.quote.strip() not in source["text"]:
        raise ValueError("근거 인용은 선택한 현재 원문에서 그대로 옮겨 주세요.")


def extract(service, workspace, research_id, manual=None):
    research = current(service, workspace, research_id)
    if research is None or not research.data.get("source_documents"):
        raise ValueError("먼저 공개 자료의 링크나 원문을 추가해 주세요.")
    sources = source_context(service, workspace, research)
    service.input_artifact_ids.add(research.id)
    extracted = Extraction.model_validate(manual if manual is not None else service.ai(
        "research_source_extract", {"company": service.ws(workspace).company,
            "role": service.ws(workspace).role, "untrusted_sources": sources}, Extraction))
    data = deepcopy(research.data)
    data.update(official_facts=[], external_evidence=[], role_signals=[], historical_jd_signals=[],
                selection_process_signals=[], inferences=[], why_now_proposals=[])
    for field in ("company_facts", "role_signals", "historical_jd_signals", "selection_process_signals"):
        for item in getattr(extracted, field):
            validate_quote(item.citation, sources)
            source = sources[item.citation.source_id]
            if field == "company_facts":
                if item.citation.source_id == JD_ID or source["category"] == "HISTORICAL_JD":
                    raise ValueError("등록한 공고·과거 공고에서 현재 회사 사실을 만들 수 없습니다. 별도 회사 자료를 연결해 주세요.")
                data["external_evidence"].append({"statement": item.statement, "source_id": item.citation.source_id,
                    "source_type": "USER_SUPPLIED", "published_at": source["published_at"],
                    "retrieved_at": source["retrieved_at"], "freshness": source["freshness"]})
            elif field == "historical_jd_signals":
                if source["category"] != "HISTORICAL_JD":
                    raise ValueError("과거·유사 공고로 분류한 자료를 연결해 주세요.")
                data[field].append({"statement": item.statement, "source_id": item.citation.source_id})
            else:
                if source["category"] == "HISTORICAL_JD":
                    raise ValueError("과거 공고 내용은 현재 직무·전형 요건과 분리해 주세요.")
                data[field].append(item.statement)
    for hypothesis in extracted.inferences:
        for citation in hypothesis.citations:
            validate_quote(citation, sources)
        data["why_now_proposals"].append(hypothesis.model_dump())
        # The current JD is stored separately from public sources. A JD-only
        # hypothesis is kept in the proposal, never promoted to company inference.
        ids = sorted({c.source_id for c in hypothesis.citations} - {JD_ID})
        if ids:
            data["inferences"].append({"text": hypothesis.text, "supporting_source_ids": ids,
                                       "confidence": hypothesis.confidence, "is_inference": True})
    data.update(extraction_citations=extracted.model_dump(), extraction_status="EXTRACTED",
                mode="QUOTED_SOURCE_RESEARCH")
    return _save_research(service, workspace, data, model="manual" if manual is not None else service.current_model)


def decision(service, workspace, payload: dict):
    entry = ResearchDecision.model_validate(payload)
    research = current(service, workspace, entry.research_id)
    if research is None or entry.confirmed is not True:
        raise ValueError("현재 조사 범위와 채용 배경을 읽고 직접 확인해 주세요.")
    sources = source_context(service, workspace, research)
    for citation in entry.citations:
        validate_quote(citation, sources)
    hypothesis = entry.hypothesis.strip()
    if entry.mode == "HYPOTHESIS":
        if len(hypothesis) < 8 or not entry.citations:
            raise ValueError("채용 배경 가설과 이를 뒷받침하는 원문 인용을 연결해 주세요.")
    elif hypothesis or entry.citations:
        raise ValueError("자료 부족으로 진행할 때는 가설을 확정하지 않고 부족한 정보를 기록해 주세요.")
    item, _ = save(service.db, service.user, workspace, "ResearchReview", {
        **entry.model_dump(), "hypothesis": hypothesis, "is_inference": True,
        "why_now_confirmed": entry.mode == "HYPOTHESIS", "scope_reviewed": True,
        "reviewed_at": now().isoformat(), "basis": research.data["scope"]["basis"],
    }, deps=[research.id])
    lock(service.db, service.user, item)
    # Legacy/manual JD-only analysis may precede the first explicit decision.
    # Its old hiring context must not silently survive this new decision.
    brief = latest(service.db, service.user, workspace, "OpportunityBrief", required=False)
    if brief and brief.status in {"ACTIVE", "LOCKED"}:
        stale(service.db, service.user, [brief.id])
        brief.status = "STALE"
        service.ws(workspace).state = "NEED_USER_ACTION"
    return item


def reviewed(service, workspace, research, required=False):
    item = latest(service.db, service.user, workspace, "ResearchReview", required=False)
    if item and item.status == "LOCKED" and item.data.get("research_id") == research.id:
        fresh(service.db, service.user, item)
        return item
    if required:
        raise ValueError("회사 조사에서 출처·채용 배경을 확인해 주세요. 자료가 부족하면 ‘확인된 정보만으로 진행’을 선택할 수 있습니다.")
    return None


def analyzer_context(research):
    # Raw pages are for extraction/quotation only, not the analyzer's instructions.
    return {key: value for key, value in research.data.items()
            if key not in {"source_documents", "extraction_citations", "why_now_proposals"}}


def jd_links(text: str) -> list[str]:
    result = []
    for candidate in re.findall(r"https://[^\s<>\"']+", text):
        try:
            url = public_url(candidate.rstrip(".,);]"))
        except ValueError:
            continue
        if url not in result:
            result.append(url)
        if len(result) == 2:
            break
    return result
