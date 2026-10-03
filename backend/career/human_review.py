"""Version-bound edit proposals. Generation never means acceptance."""

import hashlib
import json

from sqlalchemy import select

from career.db import Record
from career.schemas import Document, Patch
from career.truth import owned, view


def fingerprint(document):
    return hashlib.sha256(document.data["text"].encode()).hexdigest()


def propose_patch(service, workspace, qid, patch, resume=False, review_id=""):
    service.editable(service.ws(workspace))
    document = service.artifact(workspace, "ResumeContent" if resume else "Draft", qid)
    patch = Patch.model_validate(patch).model_dump()
    if not patch["old_text"] or document.data["text"].count(patch["old_text"]) != 1:
        raise ValueError("수정할 원문이 현재 본문에 정확히 한 곳 있어야 합니다.")
    preview = document.data["text"].replace(patch["old_text"], patch["new_text"], 1)
    if any(
        preview.count(s) < document.data["text"].count(s) for s in document.data.get("protected_spans", [])
    ):
        raise ValueError("보호된 문장을 바꾸는 제안입니다.")
    service.validate_ledger(
        {"text": preview, "claims": patch["claims"]}, service.selected(document.data["selected_evidence_ids"])
    )
    record = Record(
        user_id=service.user,
        kind="RevisionProposal",
        data={
            "workspace_id": workspace,
            "question_id": qid,
            "resume": resume,
            "artifact_id": document.id,
            "version": document.version,
            "fingerprint": fingerprint(document),
            "review_id": review_id,
            "patch": patch,
            "before": document.data["text"],
            "after": preview,
            "status": "PENDING",
            "result": None,
        },
    )
    service.db.add(record)
    service.db.flush()
    return view(record)


def proposals(service, workspace):
    service.ws(workspace)
    return [
        view(r)
        for r in service.db.scalars(
            select(Record)
            .where(Record.user_id == service.user, Record.kind == "RevisionProposal")
            .order_by(Record.created_at)
        )
        if r.data["workspace_id"] == workspace
    ]


def resolve(service, workspace, proposal_id, decision, new_text=None):
    service.editable(service.ws(workspace))
    record = owned(service.db, Record, service.user, proposal_id)
    if record.kind != "RevisionProposal" or record.data["workspace_id"] != workspace:
        raise LookupError("이 작업의 수정 제안이 아닙니다.")
    if decision not in {"ACCEPT", "REJECT"}:
        raise ValueError("반영 또는 거절을 선택해 주세요.")
    signature = {"decision": decision, "new_text": new_text}
    if record.data["status"] != "PENDING":
        if record.data.get("resolution") != signature:
            raise ValueError("이미 처리된 제안입니다.")
        return record.data["result"]
    if decision == "REJECT":
        result = {"proposal_id": record.id, "status": "REJECTED"}
    else:
        data = record.data
        current = service.artifact(
            workspace, "ResumeContent" if data["resume"] else "Draft", data["question_id"]
        )
        if current.id != data["artifact_id"] or fingerprint(current) != data["fingerprint"]:
            raise ValueError("검토 중 원문이 바뀌었습니다. 현재 버전에서 새 제안을 만들어 주세요.")
        if (
            data["review_id"]
            and service.artifact(
                workspace, "ResumeReview" if data["resume"] else "Review", data["question_id"]
            ).id
            != data["review_id"]
        ):
            raise ValueError("검수 내용이 바뀌었습니다. 새 검수 결과로 제안해 주세요.")
        patch = {**data["patch"]}
        if new_text is not None and new_text != patch["new_text"]:
            patch["new_text"] = new_text
            preview = current.data["text"].replace(patch["old_text"], new_text, 1)
            patch["claims"] = Document.model_validate(
                {
                    "text": preview,
                    "claims": [
                        {
                            "text": preview,
                            "type": "FACT",
                            "evidence_ids": current.data["selected_evidence_ids"],
                            "support": "NEEDS_REVIEW",
                            "ownership_ok": False,
                        }
                    ],
                }
            ).model_dump()["claims"]
        result = service.apply_revision(workspace, data["question_id"], patch, resume=data["resume"])
        result["proposal_id"] = record.id
        result["status"] = "ACCEPTED"
    result = json.loads(json.dumps(result, default=str))
    record.data = {**record.data, "status": result["status"], "resolution": signature, "result": result}
    return result
