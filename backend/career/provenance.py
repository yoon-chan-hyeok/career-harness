"""Resolve existing ledger links without inventing sentence-level proof."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from career.entities import MetricRecord, OwnershipRecord
from career.models import Artifact, Evidence, Fact, Source
from career.truth import owned


def artifact_provenance(db: Session, user: str, artifact_id: str):
    artifact = owned(db, Artifact, user, artifact_id)
    # A historic document must resolve the research version in its dependency
    # graph, rather than borrowing a newer company's quote with the same ID.
    research, pending, seen = [], list(artifact.depends_on), {artifact.id}
    while pending:
        ident = pending.pop()
        if ident in seen:
            continue
        seen.add(ident)
        parent = db.scalar(select(Artifact).where(Artifact.user_id == user, Artifact.id == ident,
                                                  Artifact.workspace_id == artifact.workspace_id))
        if parent is not None:
            pending.extend(parent.depends_on)
            if parent.kind == "CompanyResearchResult":
                research.append(parent)
    sources = {}
    for item in research:
        for source in item.data.get("sources", []):
            if isinstance(source, dict):
                ident = source.get("id")
                candidate = {**source, "status": item.status}
                if ident in sources and sources[ident] != candidate:
                    sources[ident] = None
                elif ident not in sources:
                    sources[ident] = candidate
    claims = list(artifact.data.get("claims", []))
    if not claims:
        for section in artifact.data.get("sections", []):
            for bullet in section.get("bullets", []):
                claims.extend(bullet.get("claims", []) or [{
                    "text": bullet.get("text", ""), "type": "UNMAPPED", "support": "NEEDS_REVIEW",
                    "ownership_ok": False, "evidence_ids": bullet.get("evidence_ids", []),
                    "profile_fact_ids": bullet.get("profile_fact_ids", []),
                }])
    items = []

    def source_view(ident):
        source = db.scalar(select(Source).where(Source.id == ident, Source.user_id == user))
        return {"id": source.id, "path": source.path, "status": source.status,
                "authority": source.authority} if source else None

    for index, claim in enumerate(claims):
        result = {"index": index, "text": claim.get("text", ""), "type": claim.get("type", "UNMAPPED"),
                  "support": claim.get("support", "NEEDS_REVIEW"),
                  "ownership_ok": claim.get("ownership_ok") is True,
                  "evidence": [], "metrics": [], "ownership": [], "profile_facts": [],
                  "company_sources": [], "missing_links": []}
        for ident in dict.fromkeys(claim.get("evidence_ids", [])):
            item = db.scalar(select(Evidence).where(Evidence.id == ident, Evidence.user_id == user))
            if item is None:
                result["missing_links"].append({"kind": "evidence", "id": ident})
                continue
            result["evidence"].append({"id": item.id, "title": item.title, "kind": item.kind,
                                       "status": item.status, "body": item.body,
                                       "source": source_view(item.source_id)})
            for record in db.scalars(select(OwnershipRecord).where(
                    OwnershipRecord.user_id == user, OwnershipRecord.evidence_id == ident)):
                result["ownership"].append({"id": record.id, "status": record.status, "data": record.data})
        for kind, model, field in [("metrics", MetricRecord, "metric_ids"), ("profile_facts", Fact, "profile_fact_ids")]:
            for ident in dict.fromkeys(claim.get(field, [])):
                item = db.scalar(select(model).where(model.user_id == user, model.id == ident))
                if item is None:
                    result["missing_links"].append({"kind": kind, "id": ident})
                elif isinstance(item, Fact):
                    result[kind].append({"id": item.id, "status": item.status, "key": item.key,
                                         "value": item.value, "source": source_view(item.source_id)})
                else:
                    result[kind].append({"id": item.id, "status": item.status, "data": item.data})
        for ident in dict.fromkeys(claim.get("company_source_ids", [])):
            source = sources.get(ident)
            if source is None:
                result["missing_links"].append({"kind": "company_source", "id": ident})
            else:
                result["company_sources"].append({"id": ident, "title": source.get("title", ""),
                                                  "url": source.get("url", ""), "quote": source.get("quote", ""),
                                                  "status": source["status"]})
        items.append(result)
    return {"artifact": {"id": artifact.id, "kind": artifact.kind, "version": artifact.version,
                         "status": artifact.status}, "items": items,
            "notice": "저장된 주장과 연결된 원자료입니다. 연결 여부는 사실·수치·본인 수행 범위의 승인을 대신하지 않습니다."}
