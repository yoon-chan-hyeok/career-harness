"""Read-only readiness and exports of the exact immutable submission bundle."""

import io
import json
import zipfile

from sqlalchemy import select

from career.artifacts import fresh, latest
from career.document_exports import render_docx, render_pdf
from career.models import Artifact
from career.workflow import Workflow


def packet_status(db, user, workspace):
    service = Workflow(db, user)
    ws = service.ws(workspace)
    bundle = latest(db, user, workspace, "SubmissionBundle", required=False)
    artifacts = list(db.scalars(select(Artifact).where(Artifact.user_id == user,
                          Artifact.workspace_id == workspace).order_by(Artifact.version)))
    current = {(item.kind, item.slot): item for item in artifacts}
    checklist = []

    def check(code, label, ok, stage, slot="", detail=""):
        checklist.append({"code": code, "label": label, "complete": ok,
                          "stage": stage, "slot": slot, "detail": detail})

    def locked(kind, slot=""):
        item = current.get((kind, slot))
        if item is None or item.status != "LOCKED":
            return False
        try:
            fresh(db, user, item)
            if kind in {"Draft", "ResumeContent"}:
                service.validate_ledger(item.data, service.selected(item.data["selected_evidence_ids"]))
        except (ValueError, LookupError):
            return False
        return True

    if bundle is None:
        check("strategy", "지원 전략 승인", locked("ApplicationBrief"), 1)
        check("documents", "제출할 문서 구성", bool(ws.data.get("questions") or ws.data.get("resume_requested")), 2)
        for index, question in enumerate(ws.data.get("questions", [])):
            slot = question["id"]
            check("question:" + slot, f"{index + 1}번 문항 검수·잠금", locked("Draft", slot) and locked("Review", slot),
                  2, slot, "현재 근거와 본문·검수 버전을 함께 확인합니다.")
        if ws.data.get("resume_requested"):
            check("resume", "이력서 검수·잠금", locked("ResumeContent") and locked("ResumeReview"), 3)
        from career.final_decision import require_pass

        final_ok = False
        try:
            require_pass(service, workspace)
            final_ok = True
        except (ValueError, LookupError):
            pass
        check("final_questions", "직업 정체성·마지막 세 질문 확인", final_ok, 4)
        portfolio = current.get(("PortfolioReview", ""))
        portfolio_ok = False
        if portfolio:
            try:
                fresh(db, user, portfolio)
                portfolio_ok = not any(i["priority"] in {"P0", "P1"} for i in portfolio.data.get("issues", []))
            except (ValueError, LookupError):
                pass
        check("portfolio", "문서 간 최종 검수", portfolio_ok, 4)
    check("frozen", "제출용 최종본 보관", bundle is not None, 4)
    check("submitted", "실제 제출 완료 확인", bool(ws.data.get("submitted_at")), 4,
          detail="다운로드·최종본 보관만으로 제출 완료가 되지 않습니다.")
    next_check = next((item for item in checklist if not item["complete"]), None)
    return {"workspace_id": ws.id, "company": ws.company, "role": ws.role,
            "basis": "FROZEN_SNAPSHOT" if bundle else "CURRENT_VERSIONS",
            "bundle_id": bundle.id if bundle else None,
            "frozen_at": bundle.data.get("frozen_at") if bundle else None,
            "submitted_at": ws.data.get("submitted_at"), "checklist": checklist,
            "next_action": next_check, "download_available": bundle is not None,
            "notice": "확인 목록은 작업 안내입니다. 최종 보관 시 서버에서 사실·승인·문서 간 검수를 다시 수행합니다."}


def download_packet(db, user, workspace):
    service = Workflow(db, user)
    service.ws(workspace)
    bundle = latest(db, user, workspace, "SubmissionBundle")
    assert bundle is not None
    data = bundle.data
    stream = io.BytesIO()
    manifest = {"bundle_id": bundle.id, "frozen_at": data["frozen_at"],
                "company": data["company"], "role": data["role"], "files": [],
                "notice": "최종 보관 시점의 문서입니다. 다운로드는 실제 제출 확인이 아닙니다."}
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for index, answer in enumerate(data.get("cover_letter_answers", []), 1):
            name = f"cover-letter-{index:02}.txt"
            archive.writestr(name, answer["answer"].encode("utf-8-sig"))
            manifest["files"].append({"file": name, "version": answer["draft_version"]})
        resumes = [item for item in data.get("artifacts", []) if item["kind"] == "ResumeContent"]
        if resumes:
            resume = max(resumes, key=lambda item: item["version"])
            for extension, render in (("pdf", render_pdf), ("docx", render_docx)):
                result = render(resume["data"])
                name = "resume." + extension
                archive.writestr(name, result.content)
                manifest["files"].append({"file": name, "version": resume["version"],
                                          "pages": result.pages, "overflow": result.overflow})
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode())
    return stream.getvalue()
