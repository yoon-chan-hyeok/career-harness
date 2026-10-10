"""A resume master is an approved reusable view, never a new fact source."""

import hashlib

from sqlalchemy import select

from career.artifacts import fresh
from career.db import Record
from career.models import Artifact
from career.truth import owned


def current_master(service):
    return service.db.scalar(
        select(Record)
        .where(Record.user_id == service.user, Record.kind == "ResumeMaster")
        .order_by(Record.created_at.desc(), Record.id.desc())
        .limit(1)
    )


def save_master(service, artifact_id):
    item = owned(service.db, Artifact, service.user, artifact_id)
    fresh(service.db, service.user, item)
    if item.kind != "ResumeContent" or item.status != "LOCKED":
        raise ValueError("직접 검토하고 최종 잠금한 이력서를 마스터로 선택해 주세요.")
    record = Record(
        user_id=service.user,
        kind="ResumeMaster",
        data={
            "artifact_id": item.id,
            "workspace_id": item.workspace_id,
            "version": item.version,
            "role": "DERIVED_CACHE_NOT_FACT_SOURCE",
        },
    )
    service.db.add(record)
    service.db.flush()
    return record


def master_context(service, selected):
    record = current_master(service)
    fallback = {
        "mode": "BUILD_FROM_CURRENT_CONFIRMED_FACTS",
        "instruction": "사용 가능한 마스터가 없으므로 확인된 원자료에서 구조를 만들고 JD에 맞게 선별한다.",
    }
    if record is None:
        return fallback, None
    try:
        item = owned(service.db, Artifact, service.user, record.data["artifact_id"])
        fresh(service.db, service.user, item)
    except (LookupError, ValueError):
        return fallback, None
    selected_set = set(selected)
    # Do not leak unrelated master facts into this application's writer.
    sections = []
    for section in item.data.get("sections", []):
        bullets = [
            b
            for b in section.get("bullets", [])
            if b.get("claims") and all(set(c.get("evidence_ids", [])) <= selected_set for c in b["claims"])
        ]
        if bullets:
            sections.append({**section, "bullets": bullets})
    return {
        "mode": "TAILOR_APPROVED_MASTER",
        "sections": sections,
        "authority": "STRUCTURE_ONLY_CURRENT_EVIDENCE_OVERRIDES",
        "version": item.version,
    }, item.id if item.workspace_id != service.current_workspace else None


def confirm_file_qa(service, workspace, artifact_id, confirmed):
    service.ws(workspace)
    item = service.artifact(workspace, "ResumeContent")
    if item.id != artifact_id or confirmed is not True:
        raise ValueError("현재 이력서 미리보기·내보낸 파일을 직접 확인해 주세요.")
    record = Record(
        user_id=service.user,
        kind="ResumeFileQA",
        data={
            "workspace_id": workspace,
            "artifact_id": item.id,
            "version": item.version,
            "fingerprint": hashlib.sha256(item.data["text"].encode()).hexdigest(),
            "confirmed": True,
            "checks": ["잘림·겹침·줄바꿈", "페이지 수·여백", "링크·날짜", "언어·파일명·형식"],
        },
    )
    service.db.add(record)
    service.db.flush()
    return record


def require_file_qa(service, item):
    digest = hashlib.sha256(item.data["text"].encode()).hexdigest()
    if not any(
        r.data["artifact_id"] == item.id and r.data["fingerprint"] == digest
        for r in service.db.scalars(
            select(Record).where(Record.user_id == service.user, Record.kind == "ResumeFileQA")
        )
    ):
        raise ValueError(
            "현재 이력서의 실제 파일에서 잘림·페이지·링크·날짜를 확인하고 파일 검토를 승인해 주세요."
        )
