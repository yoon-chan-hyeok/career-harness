"""Source-bound Decision / Experiment graphs, derived solely from explicit user-owned episodes."""

import hashlib
import json
import re
from typing import Any, Literal

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from career.db import Record
from career.entities import DecisionEpisodeRecord, OwnershipRecord
from career.models import Evidence, Source
from career.schemas import Schema
from career.truth import owned, view
from career.validation import GOOD

NodeKind = Literal[
    "PROBLEM", "CONSTRAINT", "INITIAL_HYPOTHESIS", "ALTERNATIVE", "EXPERIMENT", "OBSERVATION",
    "UNEXPECTED_RESULT", "REJECTED_HYPOTHESIS", "REDUCED_CLAIM", "REFRAMING", "DECISION", "ACTION",
    "VALIDATION", "RESULT", "LIMITATION", "INSIGHT",
]
EdgeKind = Literal[
    "EPISODE_NEXT", "TESTED_BY", "PRODUCED", "CONTRADICTED", "CAUSED", "LED_TO", "SUPPORTS",
    "REJECTED_FOR", "CONSTRAINED_BY", "VALIDATED_BY", "REDUCES", "LIMITS",
]
SearchIntent = Literal[
    "ANY", "UNEXPECTED_CHANGED_DECISION", "ABANDONED_METHOD", "FAILURE_REFRAMING",
    "CONSTRAINT_DESIGN_CHANGE", "NARROWED_HYPOTHESIS",
]
FIELD_KINDS: dict[str, NodeKind] = {
    "situation": "PROBLEM", "constraint": "CONSTRAINT", "hypothesis": "INITIAL_HYPOTHESIS",
    "options": "ALTERNATIVE", "experiment": "EXPERIMENT", "observation": "OBSERVATION",
    "unexpected_result": "UNEXPECTED_RESULT", "rejected_hypothesis": "REJECTED_HYPOTHESIS",
    "reduced_claim": "REDUCED_CLAIM", "reframe": "REFRAMING", "decision": "DECISION", "action": "ACTION",
    "validation": "VALIDATION", "outcome": "RESULT", "limitation": "LIMITATION", "lesson": "INSIGHT",
}
OWNERSHIP_KEYS = (
    "problem_definition", "hypothesis", "experiment_design", "implementation", "integration", "result_scope",
)
NODE_OWNERSHIP = {
    "situation": "problem_definition", "constraint": "problem_definition", "hypothesis": "hypothesis",
    "options": "hypothesis", "decision": "problem_definition", "action": "implementation",
    "experiment": "experiment_design", "validation": "experiment_design",
}


class GraphNode(Schema):
    id: str
    kind: NodeKind
    text: str
    entity_field: str
    source_id: str
    evidence_id: str
    episode_id: str
    exact_evidence_quote: str | None = None
    provenance_basis: Literal["EXACT_EVIDENCE_QUOTE", "USER_ENTITY_FIELD"]
    ownership_component: str
    ownership: str
    verification_status: str


class GraphEdge(Schema):
    id: str
    from_node_id: str
    to_node_id: str
    kind: EdgeKind
    source_id: str
    evidence_id: str
    quote: str | None = None
    basis: Literal["STRUCTURAL_EPISODE_ORDER", "HUMAN_CONFIRMED_RELATION"]


class EdgeProposal(Schema):
    from_node_id: str
    to_node_id: str
    kind: EdgeKind
    quote: str = Field(min_length=1, max_length=20000)


def fingerprint(episode: DecisionEpisodeRecord, evidence: Evidence, ownership: dict) -> str:
    content = [episode.id, episode.version, episode.data, evidence.id, evidence.source_id, evidence.body,
               evidence.data, ownership]
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _context(db: Session, user: str, episode_id: str):
    episode = owned(db, DecisionEpisodeRecord, user, episode_id)
    evidence = owned(db, Evidence, user, episode.evidence_id)
    sources = {episode.source_id, evidence.source_id}
    if not episode.source_id or evidence.kind == "EXPRESSION":
        raise ValueError("개인 사실 근거와 연결된 의사결정 경험만 사용할 수 있습니다.")
    for source_id in sources:
        if not source_id:
            raise ValueError("의사결정 출처를 확인해 주세요.")
        source = owned(db, Source, user, source_id)
        if source.authority in {"REFERENCE", "APPLICATION"} or source.status not in GOOD:
            raise ValueError("의사결정 원자료의 출처가 유효하지 않습니다.")
    if evidence.status not in GOOD or episode.status in {"CONFLICTED", "DO_NOT_USE", "SUPERSEDED"}:
        raise ValueError("의사결정 경험과 원자료를 먼저 확인해 주세요.")
    ownership = {key: "UNKNOWN" for key in OWNERSHIP_KEYS}
    records = list(db.scalars(select(OwnershipRecord).where(
        OwnershipRecord.user_id == user, OwnershipRecord.evidence_id == evidence.id,
        OwnershipRecord.status.in_(GOOD),
    ).order_by(OwnershipRecord.version.desc())))
    if records:
        latest = records[0]
        if latest.source_id and owned(db, Source, user, latest.source_id).status in GOOD:
            sources.add(latest.source_id)
            ownership = {key: latest.data.get(key, "UNKNOWN") for key in OWNERSHIP_KEYS}
    elif isinstance(evidence.data.get("ownership"), dict):
        ownership = {key: evidence.data["ownership"].get(key, "UNKNOWN") for key in OWNERSHIP_KEYS}
    return episode, evidence, ownership, sorted(sources)


def _records(db: Session, user: str, episode_id: str | None = None):
    records = list(db.scalars(select(Record).where(Record.user_id == user, Record.kind == "DecisionGraph")))
    return [r for r in records if episode_id is None or r.data.get("episode_id") == episode_id]


def project_episode(db: Session, user: str, episode_id: str) -> Record:
    episode, evidence, ownership, sources = _context(db, user, episode_id)
    digest = fingerprint(episode, evidence, ownership)
    existing = _records(db, user, episode_id)
    current = max(existing, key=lambda row: row.data.get("version", 0), default=None)
    if current and current.data.get("fingerprint") == digest and current.data.get("status") in {"ACTIVE", "PENDING"}:
        return current
    version = (current.data.get("version", 0) if current else 0) + 1
    verified = episode.status in GOOD
    nodes: list[GraphNode] = []
    for field, kind in FIELD_KINDS.items():
        values = episode.data.get(field, []) if field == "options" else [episode.data.get(field, "")]
        for index, value in enumerate(values):
            if not isinstance(value, str) or not value.strip():
                continue
            component = NODE_OWNERSHIP.get(field, "result_scope")
            quote = value if value in evidence.body else None
            nodes.append(GraphNode(
                id=f"{episode.id}:{version}:{field}:{index}", kind=kind, text=value, entity_field=field,
                source_id=episode.source_id, evidence_id=evidence.id, episode_id=episode.id,
                exact_evidence_quote=quote,
                provenance_basis="EXACT_EVIDENCE_QUOTE" if quote is not None else "USER_ENTITY_FIELD",
                ownership_component=component, ownership=ownership.get(component, "UNKNOWN"),
                verification_status=episode.status,
            ))
    if not nodes:
        raise ValueError("원자료에 정리된 의사결정 항목이 없습니다.")
    edges = [GraphEdge(
        id=f"{episode.id}:{version}:sequence:{index}", from_node_id=first.id, to_node_id=second.id,
        kind="EPISODE_NEXT", source_id=episode.source_id, evidence_id=evidence.id,
        basis="STRUCTURAL_EPISODE_ORDER",
    ) for index, (first, second) in enumerate(zip(nodes, nodes[1:], strict=False))]
    # A deterministic field-order link is not a causal claim. Causal relations require explicit human quotes.
    for previous in _records(db, user):
        if previous.data.get("evidence_id") == evidence.id and previous.data.get("status") in {"ACTIVE", "PENDING"}:
            previous.data = {**previous.data, "status": "SUPERSEDED"}
    record = Record(user_id=user, kind="DecisionGraph", data={
        "episode_id": episode.id, "entity_version": episode.version, "evidence_id": evidence.id,
        "source_id": episode.source_id, "source_ids": sources, "version": version, "fingerprint": digest,
        "status": "ACTIVE" if verified else "PENDING",
        "approval_status": "INHERITED_ENTITY_CONFIRMATION" if verified else "NEEDS_HUMAN_CONFIRMATION",
        "result_polarity": episode.data.get("outcome_kind", "UNKNOWN"), "ownership": ownership,
        "nodes": [node.model_dump() for node in nodes], "edges": [edge.model_dump() for edge in edges],
        "projection_version": "decision-graph-v1", "authority": "DERIVED_GRAPH_NOT_NEW_FACT",
    })
    db.add(record)
    db.flush()
    return record


def graph_view(db: Session, user: str, graph_id: str, include_stale=False) -> dict[str, Any]:
    graph = owned(db, Record, user, graph_id)
    if graph.kind != "DecisionGraph":
        raise LookupError("의사결정 그래프가 아닙니다.")
    data = dict(graph.data)
    try:
        episode, evidence, ownership, sources = _context(db, user, data["episode_id"])
        valid = data.get("fingerprint") == fingerprint(episode, evidence, ownership)
        valid = valid and data.get("source_ids") == sources
    except (LookupError, ValueError, KeyError):
        valid = False
    if not valid and data.get("status") in {"ACTIVE", "PENDING"}:
        data["status"] = "STALE"
    if data.get("status") in {"STALE", "SUPERSEDED", "DO_NOT_USE"} and not include_stale:
        data["nodes"], data["edges"] = [], []
    return {**view(graph), "data": data}


def approve_graph(db: Session, user: str, graph_id: str, confirmed: bool) -> dict[str, Any]:
    graph = owned(db, Record, user, graph_id)
    current = graph_view(db, user, graph_id)
    if not confirmed or current["data"].get("status") not in {"PENDING", "ACTIVE"}:
        raise ValueError("현재 의사결정 그래프를 읽고 직접 확인한 경우에만 승인할 수 있습니다.")
    episode, evidence, ownership, _ = _context(db, user, graph.data["episode_id"])
    if episode.status not in GOOD:
        episode.status = "USER_CONFIRMED"
    data = {**graph.data, "status": "ACTIVE", "approval_status": "HUMAN_CONFIRMED",
            "fingerprint": fingerprint(episode, evidence, ownership)}
    data["nodes"] = [{**node, "verification_status": "USER_CONFIRMED"} for node in data["nodes"]]
    graph.data = data
    db.add(Record(user_id=user, kind="DecisionGraphApproval", data={
        "graph_id": graph.id, "graph_version": data["version"], "episode_id": episode.id,
        "source_id": data["source_id"], "confirmed": True,
    }))
    db.flush()
    return graph_view(db, user, graph_id)


def add_relations(db: Session, user: str, graph_id: str, edges: list[EdgeProposal]) -> dict[str, Any]:
    previous = owned(db, Record, user, graph_id)
    current = graph_view(db, user, graph_id)
    if current["data"].get("status") not in {"ACTIVE", "PENDING"}:
        raise ValueError("현재 원자료에 맞춰 의사결정 흐름을 새로 정리해 주세요.")
    episode, evidence, _, _ = _context(db, user, previous.data["episode_id"])
    nodes = {node["id"] for node in previous.data["nodes"]}
    signatures = set()
    additions = []
    for edge in edges:
        signature = (edge.from_node_id, edge.to_node_id, edge.kind)
        if edge.from_node_id not in nodes or edge.to_node_id not in nodes or edge.from_node_id == edge.to_node_id:
            raise ValueError("같은 그래프의 서로 다른 항목을 연결해 주세요.")
        if edge.quote not in evidence.body or signature in signatures or edge.kind == "EPISODE_NEXT":
            raise ValueError("원자료의 정확한 인용과 중복 없는 의미 관계가 필요합니다.")
        signatures.add(signature)
        additions.append(GraphEdge(
            id=f"{previous.id}:relation:{len(additions)}", **edge.model_dump(),
            source_id=episode.source_id, evidence_id=evidence.id, basis="HUMAN_CONFIRMED_RELATION",
        ).model_dump())
    if not additions:
        raise ValueError("추가할 의미 관계를 입력해 주세요.")
    data = {**previous.data, "version": previous.data["version"] + 1, "status": "PENDING",
            "approval_status": "NEEDS_HUMAN_CONFIRMATION", "edges": previous.data["edges"] + additions}
    previous.data = {**previous.data, "status": "SUPERSEDED"}
    record = Record(user_id=user, kind="DecisionGraph", data=data)
    db.add(record)
    db.flush()
    return graph_view(db, user, record.id)


def invalidate_graphs(
    db: Session, user: str, source_ids: set[str] | None = None, evidence_ids: set[str] | None = None,
    delete_content=False,
) -> list[str]:
    changed = []
    for graph in _records(db, user):
        if (
            set(graph.data.get("source_ids", [])).intersection(source_ids or set())
            or graph.data.get("evidence_id") in (evidence_ids or set())
        ):
            graph.data = {**graph.data, "status": "DO_NOT_USE" if delete_content else "STALE"}
            if delete_content:
                graph.data = {**graph.data, "nodes": [], "edges": [], "ownership": {}}
            changed.append(graph.id)
    return changed


def _intent_matches(data: dict, intent: SearchIntent) -> bool:
    kinds = {node["kind"] for node in data.get("nodes", [])}
    requirements = {
        "UNEXPECTED_CHANGED_DECISION": {"UNEXPECTED_RESULT", "DECISION"},
        "ABANDONED_METHOD": {"ALTERNATIVE", "REJECTED_HYPOTHESIS"},
        "FAILURE_REFRAMING": {"REFRAMING", "RESULT"},
        "CONSTRAINT_DESIGN_CHANGE": {"CONSTRAINT", "DECISION", "ACTION"},
        "NARROWED_HYPOTHESIS": {"INITIAL_HYPOTHESIS", "REDUCED_CLAIM"},
    }
    return (intent == "ANY" or requirements[intent] <= kinds) and (
        intent != "FAILURE_REFRAMING" or data.get("result_polarity") == "NEGATIVE"
    )


def search_graphs(db: Session, user: str, query="", intent: SearchIntent = "ANY", limit=20) -> list[dict]:
    if intent not in {"ANY", "UNEXPECTED_CHANGED_DECISION", "ABANDONED_METHOD", "FAILURE_REFRAMING",
                      "CONSTRAINT_DESIGN_CHANGE", "NARROWED_HYPOTHESIS"} or not 1 <= limit <= 100:
        raise ValueError("지원하는 경험 검색 유형과 검색 개수를 선택해 주세요.")
    tokens = set(re.findall(r"[\w가-힣]+", query.lower()))
    results = []
    for graph in _records(db, user):
        item = graph_view(db, user, graph.id)
        data = item["data"]
        if data.get("status") != "ACTIVE" or not _intent_matches(data, intent):
            continue
        matched = [node for node in data["nodes"] if any(token in node["text"].lower() for token in tokens)]
        if tokens and not matched:
            continue
        results.append({**item, "matched_node_ids": [node["id"] for node in matched],
                        "search_basis": "EXPLICIT_EPISODE_FIELDS_NOT_JOB_FIT",
                        "search_score": len(matched)})
    results.sort(key=lambda row: (-row["search_score"], row["id"]))
    return results[:limit]
