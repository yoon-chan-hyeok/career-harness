import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from career.db import Record
from career.models import Evidence, Fact, Source
from career.validation import GOOD

POLICIES = {
    "profile": ["USER_CORRECTION", "OFFICIAL", "MASTER", "APPLICATION", "MEMORY"],
    "metric": ["RAW_RESULT", "LOCKED_PROJECT", "MASTER", "APPLICATION", "MEMORY", "USER_CORRECTION"],
    "ownership": ["USER_CORRECTION", "LOCKED_PROJECT", "REPOSITORY", "APPLICATION", "MEMORY"],
    "company": ["OFFICIAL", "EXTERNAL", "MEMORY"],
}


def owned(db: Session, model, user: str, ident: str):
    row = db.scalar(select(model).where(model.user_id == user, model.id == ident))
    if row is None:
        raise LookupError("찾을 수 없는 항목입니다.")
    return row


def view(row) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def register_source(db: Session, user: str, path: str, content: str, authority: str, data=None):
    digest = hashlib.sha256(content.encode()).hexdigest()
    existing = db.scalar(
        select(Source).where(Source.user_id == user, Source.path == path, Source.content_hash == digest)
    )
    if existing:
        return existing, False
    source = Source(user_id=user, path=path, content_hash=digest, authority=authority, data=data or {})
    db.add(source)
    db.flush()
    return source, True


def invalidate_source(db: Session, user: str, source_id: str, delete_content=False):
    from career.artifacts import stale
    from career.entities import ENTITY_MODELS

    sources = list(db.scalars(select(Source).where(Source.user_id == user)))
    affected = {source_id}
    for _ in sources:
        children = {s.id for s in sources if s.data.get("parent_source_id") in affected}
        if children <= affected:
            break
        affected |= children
    changed = stale(db, user, list(affected))
    for source in sources:
        if source.id in affected:
            source.status = "DO_NOT_USE" if delete_content else "SUPERSEDED"
            if delete_content:
                source.path, source.data = "[deleted:" + source.id + "]", {}
    for model in (Fact, Evidence):
        for item in db.scalars(select(model).where(model.user_id == user, model.source_id.in_(affected))):
            item.status = "DO_NOT_USE" if delete_content else "SUPERSEDED"
            if delete_content:
                if isinstance(item, Evidence):
                    item.body, item.data = "[삭제된 출처]", {}
                else:
                    item.value = {}
    secondary_evidence = set()
    for model in ENTITY_MODELS.values():
        for entity in db.scalars(select(model).where(model.user_id == user, model.source_id.in_(affected))):
            if entity.evidence_id:
                secondary_evidence.add(entity.evidence_id)
            entity.status = "DO_NOT_USE" if delete_content else "SUPERSEDED"
            entity.data = {} if delete_content else {**entity.data, "status": entity.status}
    for evidence_id in secondary_evidence:
        evidence = owned(db, Evidence, user, evidence_id)
        if evidence.source_id not in affected:
            evidence.status = "CONFLICTED"
            changed.extend(stale(db, user, [evidence.source_id]))
    from career.decision_graph import invalidate_graphs

    invalidate_graphs(db, user, source_ids=affected, evidence_ids=secondary_evidence, delete_content=delete_content)
    if delete_content:
        from career.projections import CorrectionRecord

        if db.bind is not None and db.bind.dialect.name == "postgresql":
            for source_ident in affected:
                db.execute(
                    text(
                        "DELETE FROM evidence_embeddings WHERE user_id=:user AND evidence_id IN (SELECT id FROM evidences WHERE user_id=:user AND source_id=:source)"
                    ),
                    {"user": user, "source": source_ident},
                )

        for correction in db.scalars(
            select(CorrectionRecord).where(
                CorrectionRecord.user_id == user, CorrectionRecord.source_id.in_(affected)
            )
        ):
            correction.data = {}
        for record in db.scalars(select(Record).where(Record.user_id == user)):
            if record.data.get("source_id") in affected:
                db.delete(record)
    return changed


def add_fact(
    db: Session,
    user: str,
    source_id: str,
    fact_type: str,
    key: str,
    value: dict,
    status: str = "SOURCE_BACKED",
) -> Fact:
    source = owned(db, Source, user, source_id)
    if source.status not in GOOD:
        raise ValueError("출처 확인이 필요합니다.")
    if source.authority == "REFERENCE":
        raise ValueError("추가 규칙·표현 참고 자료는 사실 근거로 등록할 수 없습니다.")
    if source.authority == "APPLICATION":
        status = "UNVERIFIED"
    previous = list(
        db.scalars(
            select(Fact).where(
                Fact.user_id == user, Fact.key == key, Fact.fact_type == fact_type, Fact.status.in_(GOOD)
            )
        )
    )
    policy = POLICIES.get(fact_type, ["RAW_RESULT", "LOCKED_PROJECT", "MASTER", "USER_CORRECTION", "MEMORY"])

    def rank(s):
        return policy.index(s.authority) if s.authority in policy else len(policy)

    fact = Fact(user_id=user, source_id=source.id, fact_type=fact_type, key=key, value=value, status=status)
    pending_corrections = [
        f
        for f in db.scalars(
            select(Fact).where(
                Fact.user_id == user,
                Fact.fact_type == fact_type,
                Fact.key == key,
                Fact.status == "CONFLICTED",
            )
        )
        if owned(db, Source, user, f.source_id).authority == "USER_CORRECTION"
    ]
    if fact_type == "metric" and pending_corrections and status in GOOD:
        fact.status = "CONFLICTED"
    for old in previous:
        old_source = owned(db, Source, user, old.source_id)
        if old.value == value:
            continue
        if status in GOOD and source.authority == "USER_CORRECTION" and fact_type == "metric":
            # A latest explicit correction blocks the old measurement; it does not
            # silently assert that a newly stated number is an experimental result.
            old.status = "CONFLICTED"
            fact.status = "CONFLICTED"
            from career.artifacts import stale

            stale(db, user, [old.source_id])
            for related in db.scalars(
                select(Evidence).where(Evidence.user_id == user, Evidence.source_id == old.source_id)
            ):
                related.status = "CONFLICTED"
        elif (
            status in GOOD
            and rank(source) < rank(old_source)
            or (status in GOOD and source.authority == "USER_CORRECTION" and fact_type != "metric")
        ):
            old.status = "SUPERSEDED"
            fact.supersedes_id = old.id
            from career.artifacts import stale

            stale(db, user, [old.source_id])
        elif rank(source) > rank(old_source) or status not in GOOD:
            fact.status = "SUPERSEDED" if status in GOOD else status
        else:
            old.status = "CONFLICTED"
            fact.status = "CONFLICTED"
        db.add(
            Record(
                user_id=user,
                kind="truth_conflict",
                data={"key": key, "old_fact_id": old.id, "source_id": source.id, "resolution": fact.status},
            )
        )
    db.add(fact)
    db.flush()
    if source.authority == "USER_CORRECTION":
        from career.projections import CorrectionRecord

        db.add(
            CorrectionRecord(
                user_id=user,
                source_id=source_id,
                fact_id=fact.id,
                key=key,
                data={
                    "fact_type": fact_type,
                    "value": value,
                    "status": fact.status,
                    "supersedes_id": fact.supersedes_id,
                },
            )
        )
    return fact


def canonical(db: Session, user: str):
    facts = list(
        db.scalars(select(Fact).where(Fact.user_id == user, Fact.status.in_(GOOD)).order_by(Fact.created_at))
    )
    return {
        f"{f.fact_type}:{f.key}": view(f)
        for f in facts
        if owned(db, Source, user, f.source_id).status in GOOD
    }


def resolve_fact_conflict(db: Session, user: str, fact_id: str, confirmed: bool):
    fact = owned(db, Fact, user, fact_id)
    if (
        not confirmed
        or fact.status != "CONFLICTED"
        or owned(db, Source, user, fact.source_id).status not in GOOD
    ):
        raise ValueError("충돌한 값과 출처를 직접 대조하고 사용할 값을 선택해 주세요.")
    from career.artifacts import stale

    conflicts = list(
        db.scalars(
            select(Fact)
            .where(
                Fact.user_id == user,
                Fact.fact_type == fact.fact_type,
                Fact.key == fact.key,
                Fact.status.in_(["CONFLICTED", *GOOD]),
            )
            .with_for_update()
        )
    )
    for other in conflicts:
        if other.id != fact.id:
            other.status = "SUPERSEDED"
            stale(db, user, [other.source_id])
    fact.status = "USER_CONFIRMED"
    record = Record(
        user_id=user,
        kind="FactConflictResolution",
        data={
            "fact_id": fact.id,
            "source_id": fact.source_id,
            "fact_type": fact.fact_type,
            "key": fact.key,
            "value": fact.value,
            "confirmed": True,
        },
    )
    db.add(record)
    return view(fact)


def add_evidence(
    db: Session,
    user: str,
    source_id: str,
    title: str,
    body: str,
    data=None,
    status="UNVERIFIED",
    kind="EVIDENCE",
):
    source = owned(db, Source, user, source_id)
    if source.status not in GOOD:
        raise ValueError("사용할 수 없는 출처입니다.")
    if source.authority == "REFERENCE":
        raise ValueError("추가 자료의 예시를 경험 사실로 등록할 수 없습니다.")
    if source.authority == "APPLICATION":
        kind, status = "EXPRESSION", "UNVERIFIED"
    evidence = Evidence(
        user_id=user, source_id=source.id, title=title, body=body, data=data or {}, status=status, kind=kind
    )
    db.add(evidence)
    db.flush()
    return evidence


def import_corpus(db: Session, user: str, root: Path):
    summary: dict[str, Any] = {"sources_added": 0, "skipped": 0, "errors": [], "unconfirmed_records": 0}
    root = root.resolve()
    for path in sorted(root.rglob("*")):
        if (
            not path.is_file()
            or path.suffix.lower() not in {".json", ".jsonl", ".md", ".txt"}
            or path.name == "README.md"
            or "supplemental" in path.relative_to(root).parts
        ):
            continue
        if not path.resolve().is_relative_to(root):
            continue
        try:
            with db.begin_nested():
                content = path.read_text("utf-8-sig")
                relative = path.relative_to(root).as_posix()
                category = relative.split("/")[0]
                authority = {
                    "corrections": "USER_CORRECTION",
                    "project_records": "LOCKED_PROJECT",
                    "master_resume": "MASTER",
                    "final_applications": "APPLICATION",
                }.get(category, "MEMORY")
                source, added = register_source(db, user, relative, content, authority)
                if not added:
                    summary["skipped"] += 1
                    continue
                previous = list(
                    db.scalars(
                        select(Source).where(
                            Source.user_id == user,
                            Source.path == relative,
                            Source.id != source.id,
                            Source.status.in_(GOOD),
                        )
                    )
                )
                for old_source in previous:
                    invalidate_source(db, user, old_source.id)
                from career.parsers import registry

                rows = registry.parse(path.suffix, category, content)
                for index, item in enumerate(rows):
                    if not isinstance(item, dict):
                        continue
                    kind = str(item.get("type", "IMPORTED_RECORD"))
                    # Imported summaries retain their original provenance; they are not user confirmation.
                    db.add(
                        Record(
                            user_id=user,
                            kind=kind,
                            data={"source_id": source.id, "original": item, "line": index + 1},
                        )
                    )
                    if kind in {"FACT", "PROFILE_FACT", "FACT_CORRECTION", "USER_CORRECTION"} and item.get(
                        "target"
                    ):
                        fact_source = source
                        if (
                            kind in {"FACT_CORRECTION", "USER_CORRECTION"}
                            and item.get("status") == "canonical"
                        ):
                            fact_source, _ = register_source(
                                db,
                                user,
                                relative + "#" + str(item.get("id", index)),
                                json.dumps(item, ensure_ascii=False),
                                "USER_CORRECTION",
                                {"parent_source_id": source.id, "original_source_id": item.get("source_id")},
                            )
                        fact_status = (
                            "SOURCE_BACKED"
                            if item.get("status") == "canonical" and category != "final_applications"
                            else "UNVERIFIED"
                        )
                        add_fact(
                            db,
                            user,
                            fact_source.id,
                            "profile",
                            item["target"],
                            {"text": item.get("statement", "")},
                            fact_status,
                        )
                    if kind in {
                        "PROJECT_FACT",
                        "PROJECT_CANONICAL",
                        "PROJECT_METRIC",
                        "PROJECT_CHARACTER",
                        "EVIDENCE",
                        "DECISION_EPISODE",
                        "PROJECT",
                        "EXPRESSION",
                    } or category in {"project_records", "master_resume", "final_applications"}:
                        body = (
                            item.get("statement") or item.get("body") or json.dumps(item, ensure_ascii=False)
                        )
                        boundaries = [
                            r.get("statement", "")
                            for r in rows
                            if isinstance(r, dict)
                            and r.get("type") == "CLAIM_BOUNDARY"
                            and r.get("scope") == item.get("scope")
                        ]
                        add_evidence(
                            db,
                            user,
                            source.id,
                            str(item.get("scope") or item.get("target") or path.stem),
                            body,
                            {
                                "original": item,
                                "ownership": item.get("ownership", {}),
                                "forbidden_claims": item.get("forbidden_claims", []),
                                "claim_boundaries": boundaries,
                            },
                            "UNVERIFIED",
                            "EXPRESSION" if category == "final_applications" else kind,
                        )
                    summary["unconfirmed_records"] += 1
                summary["sources_added"] += 1
        except (UnicodeError, ValueError, OSError) as exc:
            summary["errors"].append({"path": path.name, "error": type(exc).__name__})
    db.flush()
    summary["conflicts"] = [
        r.data
        for r in db.scalars(select(Record).where(Record.user_id == user, Record.kind == "truth_conflict"))
    ]
    return summary
