"""Versioned whole-document review without freezing or approving documents."""

import hashlib
import json
import re

from career.artifacts import fresh, latest, save
from career.document_qa import cross_document_qa, portfolio_qa
from career.models import Source
from career.provider_config import provider_available
from career.references import references
from career.rulebook import sections
from career.schemas import Review
from career.truth import canonical, owned
from career.validation import GOOD


def policy(service):
    selected = []
    for ref in references(service.db, service.user):
        if ref.data["key"] != "cover" or not ref.data["active"]:
            continue
        if owned(service.db, Source, service.user, ref.data["source_id"]).status not in GOOD:
            continue
        for section in sections(ref.data["content"]):
            normalized = re.sub(r"\s+", "", section.text).casefold()
            if (
                section.number == "5-4"
                and not section.excluded
                and "금지" in normalized
                and all(phrase in normalized for phrase in ("같은fact", "같은숫자", "같은결론", "같은메시지"))
            ):
                selected.append(
                    {
                        "source_id": ref.data["source_id"],
                        "content_hash": ref.data["content_hash"],
                        "start_line": section.start_line,
                        "end_line": section.end_line,
                    }
                )
    return {"strict_repetition": bool(selected), "sources": selected}


def inputs(service, workspace):
    ws = service.ws(workspace)
    documents = []
    briefs = []
    missing = []
    for index, question in enumerate(ws.data.get("questions", [])):
        doc = latest(service.db, service.user, workspace, "Draft", question["id"], required=False)
        brief = latest(service.db, service.user, workspace, "QuestionBrief", question["id"], required=False)
        if doc is None:
            missing.append(f"자소서 {index + 1}번")
            continue
        fresh(service.db, service.user, doc)
        documents.append((doc, f"자소서 {index + 1}번"))
        if brief:
            fresh(service.db, service.user, brief)
            briefs.append(brief)
    if ws.data.get("resume_requested"):
        doc = latest(service.db, service.user, workspace, "ResumeContent", required=False)
        if doc:
            fresh(service.db, service.user, doc)
            documents.append((doc, "레쥬메"))
        else:
            missing.append("레쥬메")
    if not documents:
        raise ValueError("먼저 비교할 자소서나 레쥬메 본문을 작성해 주세요.")
    evidence_ids = sorted({ident for doc, _ in documents for ident in doc.data["selected_evidence_ids"]})
    evidence = service.selected(evidence_ids)
    selected_policy = policy(service)
    identity = {
        "documents": [{"id": d.id, "version": d.version} for d, _ in documents],
        "briefs": [{"id": b.id, "version": b.version} for b in briefs],
        "evidence": [
            {"id": e["id"], "status": e["status"], "body": e["body"], "data": e["data"]} for e in evidence
        ],
        "policy": selected_policy,
        "missing": missing,
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return documents, briefs, evidence, selected_policy, missing, digest


def current(service, workspace):
    item = latest(service.db, service.user, workspace, "PortfolioReview", required=False)
    if item is None:
        return None
    try:
        fresh(service.db, service.user, item)
        *_, digest = inputs(service, workspace)
    except (ValueError, LookupError):
        return None
    return item if item.data.get("context_hash") == digest else None


def run(service, workspace, *, manual_verified=False):
    ws = service.ws(workspace)
    service.editable(ws)
    documents, briefs, evidence, selected_policy, missing, digest = inputs(service, workspace)
    comparisons = [{**doc.data, "document_id": doc.id, "document_label": label} for doc, label in documents]
    issues = portfolio_qa(
        [b.data for b in briefs],
        [data for (doc, _), data in zip(documents, comparisons, strict=True) if doc.kind == "Draft"],
        strict_repetition=selected_policy["strict_repetition"],
    )
    issues.extend(cross_document_qa(comparisons, evidence))
    if missing:
        issues.append(
            {
                "code": "PORTFOLIO_INCOMPLETE",
                "priority": "P2",
                "message": "아직 작성하지 않은 문서가 있습니다: " + ", ".join(missing),
            }
        )
    semantic_enabled = not manual_verified and (service.provider is not None or provider_available())
    followups = []
    if semantic_enabled:
        semantic = service.ai(
            "cross_document_consistency",
            {
                "task": "Compare only the same fact/metric identity and measurement scope. Distinguish baseline/result and equivalent units. Repeating the same project in different roles is permitted. Compare exact facts, metrics, ownership and conclusions; ambiguous associations need P2 clarification, not invented P0/P1 contradictions.",
                "briefs": [b.data for b in briefs],
                "documents": comparisons,
                "evidence": evidence,
                "canonical_profile": canonical(service.db, service.user),
                "repetition_policy": selected_policy,
            },
            Review,
        )
        issues.extend(semantic["issues"])
        followups = semantic["followups"]
        issues.extend(
            {"code": "PORTFOLIO_FOLLOWUP", "priority": "P2", "message": question} for question in followups
        )
    blocked = any(issue["priority"] in {"P0", "P1"} for issue in issues)
    result = "NEEDS_REVISION" if blocked else "WARNINGS" if issues else "PASSED"
    item, _ = save(
        service.db,
        service.user,
        workspace,
        "PortfolioReview",
        {
            "issues": issues,
            "followups": followups,
            "result": result,
            "mode": "AI_AND_DETERMINISTIC" if semantic_enabled else "DETERMINISTIC",
            "checked_documents": [
                {"label": label, "document_id": doc.id, "version": doc.version} for doc, label in documents
            ],
            "complete": not missing,
            "context_hash": digest,
            "repetition_policy": selected_policy,
        },
        deps=[doc.id for doc, _ in documents] + [b.id for b in briefs],
        sources=sorted(
            {source for e in evidence for source in e["context_source_ids"]}
            | {source["source_id"] for source in selected_policy["sources"]}
        ),
        model=service.current_model if semantic_enabled else "manual",
    )
    if ws.state == "READY_TO_FREEZE" and blocked:
        ws.state = "NEED_USER_ACTION"
    return item
