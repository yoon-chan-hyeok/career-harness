# ruff: noqa: F811 -- reusable authenticated and workflow fixtures
from copy import deepcopy

import pytest
from career.artifacts import fresh, latest
from career.assessment import rankings
from career.document_uploads import UploadDecision, confirm_upload, upload_preview
from career.models import Artifact, Evidence, Workspace
from career.resume_master import master_context, save_master
from career.truth import add_fact, register_source
from career.validation import hard_qa
from test_api import client  # noqa: F401
from test_profile_resume import profile
from test_upgrade_documents import upload_body
from test_workflow import doc, finish, flow, question  # noqa: F401


def test_conflicting_profile_invalidates_locked_document_and_blocks_freeze(flow):
    f, w, e = flow
    fact = profile(f.db, f.user)
    f.approve_strategy(w.id)
    q = question(f, w, e)
    f.approve_question(w.id, q["id"])
    data = doc(e)
    data["text"] += "\n" + fact.value["text"]
    data["claims"].append({"text": fact.value["text"], "type": "FACT", "evidence_ids": [],
                           "profile_fact_ids": [fact.id], "support": "SUPPORTED", "ownership_ok": True})
    document = f.draft(w.id, q["id"], data)
    f.review(w.id, q["id"], manual_verified=True)
    f.final_lock(w.id, q["id"])
    from final_review_fixture import confirm_final

    confirm_final(f, w.id)
    f.ready(w.id)
    source, _ = register_source(f.db, f.user, "new-official", "2025 졸업", "OFFICIAL")
    add_fact(f.db, f.user, source.id, "profile", "education", {"text": "2025 졸업"})
    assert fact.status == "CONFLICTED" and document.status == "STALE"
    with pytest.raises(ValueError):
        f.freeze(w.id)
    # Defense for legacy locked rows predating the invalidation fix.
    document.status = "LOCKED"
    with pytest.raises(ValueError, match="프로필"):
        fresh(f.db, f.user, document)


def test_conflict_preserves_already_frozen_snapshot(flow):
    f, w, e = flow
    fact = profile(f.db, f.user)
    finish(f, w, e)
    from final_review_fixture import confirm_final

    confirm_final(f, w.id)
    f.ready(w.id)
    bundle = f.freeze(w.id)
    snapshot = deepcopy(bundle.data)
    source, _ = register_source(f.db, f.user, "conflict", "different", "OFFICIAL")
    add_fact(f.db, f.user, source.id, "profile", fact.key, {"text": "different"})
    assert bundle.data == snapshot and bundle.status == "LOCKED"


def test_uploaded_and_legacy_ownership_survive_actual_review_and_correction(flow):
    from career.api import confirm_evidence

    f, w, _ = flow
    preview = upload_preview(f.db, f.user, upload_body("experience.txt", "분석 보고서를 작성했습니다.".encode()))
    saved = confirm_upload(f.db, f.user, preview["id"], UploadDecision(title="분석", confirmed=True))
    e = f.db.get(Evidence, saved["evidence"]["id"])
    assert e is not None
    confirm_evidence(e.id, {"confirmed": True}, f.db, f.user)
    for value in ({"implementation": "UNKNOWN"}, "UNKNOWN"):
        e.data = {**e.data, "ownership": value}
        evidence = f.selected([e.id])
        assert not hard_qa(e.body, evidence)
        assert any(i["code"] == "OWNERSHIP" for i in hard_qa("전부 직접 구현", evidence))
    f.command(w.id, "이건 내가 한 거 아님", evidence_id=e.id)
    assert e.data["ownership"]["implementation"] == "UNKNOWN"


def test_same_workspace_master_does_not_poison_regeneration(flow):
    f, w, e = flow
    f.approve_strategy(w.id)
    first = f.resume(w.id, doc(e))
    f.review(w.id, resume=True, manual_verified=True)
    f.final_lock(w.id, resume=True)
    save_master(f, first.id)
    second = f.resume(w.id, doc(e))
    assert first.status == "SUPERSEDED"
    fresh(f.db, f.user, second)
    f.review(w.id, resume=True, manual_verified=True)
    assert master_context(f, [e.id])[0]["mode"] == "BUILD_FROM_CURRENT_CONFIRMED_FACTS"
    third = f.resume(w.id, doc(e))
    fresh(f.db, f.user, third)


def test_resume_regeneration_retains_protected_spans_before_any_version_write(flow):
    f, w, e = flow
    f.approve_strategy(w.id)
    first = f.resume(w.id, doc(e))
    first.data = {**first.data, "protected_spans": ["80%"]}
    changed = doc(e)
    changed["text"] = changed["text"].replace("80%", "")
    changed["claims"][0]["text"] = changed["text"]
    with pytest.raises(ValueError, match="보호"):
        f.resume(w.id, changed)
    current = latest(f.db, f.user, w.id, "ResumeContent")
    assert current is not None and current.id == first.id
    assert first.status == "ACTIVE"
    assert f.resume(w.id, doc(e)).data["protected_spans"] == ["80%"]


def test_expired_high_priority_moves_after_open_without_rewriting_assessment(db):
    assessments = []
    for name, deadline, priority in [("closed", "2020-01-01T00:00:00+00:00", "HIGH"),
                                     ("open", "2099-01-01T00:00:00+00:00", "LOW")]:
        ws = Workspace(user_id="a", company=name, role="role", jd_raw="jd", data={})
        db.add(ws)
        db.flush()
        db.add(Artifact(user_id="a", workspace_id=ws.id, kind="OpportunityBrief", version=1,
                        data={"deadline_at": deadline, "posting_status": "OPEN"}))
        a = Artifact(user_id="a", workspace_id=ws.id, kind="OpportunityAssessment", version=1,
                     data={"fit": {"level": "HIGH"}, "career_value": {"level": "HIGH"},
                           "action_priority": {"level": priority}, "recommendation": "PROCEED"})
        db.add(a)
        assessments.append(a)
    db.flush()
    result = rankings(db, "a")
    assert [r["company"] for r in result["action_order"]] == ["open", "closed"]
    assert result["action_order"][1]["current_deadline_status"] == "EXPIRED"
    assert assessments[0].data["recommendation"] == "PROCEED"


def test_server_seed_import_is_not_available_to_invited_users(client, monkeypatch):
    monkeypatch.setenv("CAREER_LOCAL_OWNER_USER", "alice")
    client.headers["Authorization"] = "Bearer bob-key"
    assert client.post("/api/sources/import").status_code == 403


def test_packet_is_exact_frozen_version_and_never_confirms_submission(flow):
    import io
    import json
    import zipfile

    from career.application_packet import download_packet, packet_status

    f, w, e = flow
    assert not packet_status(f.db, f.user, w.id)["download_available"]
    finish(f, w, e)
    f.resume(w.id, doc(e))
    f.review(w.id, resume=True, manual_verified=True)
    f.final_lock(w.id, resume=True)
    from final_review_fixture import confirm_final

    confirm_final(f, w.id)
    f.ready(w.id)
    bundle = f.freeze(w.id)
    snapshot = deepcopy(bundle.data)
    e.body = "Later changed source must not enter export"
    archive = zipfile.ZipFile(io.BytesIO(download_packet(f.db, f.user, w.id)))
    assert set(archive.namelist()) == {"cover-letter-01.txt", "resume.pdf", "resume.docx", "manifest.json"}
    assert archive.read("cover-letter-01.txt").decode("utf-8-sig") == snapshot["cover_letter_answers"][0]["answer"]
    assert json.loads(archive.read("manifest.json"))["bundle_id"] == bundle.id
    assert w.state == "SUBMISSION_FROZEN" and bundle.data == snapshot
    assert packet_status(f.db, f.user, w.id)["next_action"]["code"] == "submitted"
    with pytest.raises(LookupError):
        download_packet(f.db, "other", w.id)


def test_packet_http_is_owner_scoped_and_read_only(client):
    client.headers["Authorization"] = "Bearer alice-key"
    ws = client.post("/api/applications", json={"company": "test", "role": "test", "jd_raw": "test"}).json()
    path = f"/api/applications/{ws['id']}/packet"
    assert client.get(path).status_code == 200
    assert client.get(path + "/download").status_code == 409
    client.headers["Authorization"] = "Bearer bob-key"
    assert client.get(path).status_code == 404
    assert client.get(path + "/download").status_code == 404
