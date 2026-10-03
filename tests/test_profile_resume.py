# ruff: noqa: F811 -- reusable workflow fixture
import pytest
from career.resume import ResumeContent, structured_document
from career.truth import add_fact, canonical, register_source
from career.validation import hard_qa
from test_workflow import flow  # noqa: F401


def profile(db, user):
    source, _ = register_source(db, user, "profile-master", "2020.03–2024.02 예시대학교 학사", "OFFICIAL")
    return add_fact(db, user, source.id, "profile", "education", {"text": "2020.03–2024.02 예시대학교 학사"})


def test_canonical_dates_are_allowed_only_in_exact_profile_context(flow):
    service, _, evidence = flow
    item = profile(service.db, service.user)
    current = canonical(service.db, service.user)
    assert not hard_qa(item.value["text"], service.selected([evidence.id]), profile=current)
    assert any(
        i["code"] == "UNSUPPORTED_METRIC"
        for i in hard_qa(
            item.value["text"] + "\n2024건 처리", service.selected([evidence.id]), profile=current
        )
    )
    assert any(
        i["code"] == "UNSUPPORTED_METRIC"
        for i in hard_qa("2025.02 예시대학교 학사", service.selected([evidence.id]), profile=current)
    )


def test_profile_only_education_bullet_keeps_fact_ids_and_disallows_metric_reuse(flow):
    service, ws, _ = flow
    service.approve_strategy(ws.id)
    item = profile(service.db, service.user)
    claim = {
        "text": item.value["text"],
        "type": "FACT",
        "evidence_ids": [],
        "profile_fact_ids": [item.id],
        "support": "SUPPORTED",
        "ownership_ok": True,
    }
    content = ResumeContent.model_validate(
        {
            "sections": [
                {
                    "title": "학력",
                    "kind": "EDUCATION",
                    "bullets": [
                        {
                            "text": claim["text"],
                            "evidence_ids": [],
                            "profile_fact_ids": [item.id],
                            "claims": [claim],
                        }
                    ],
                }
            ]
        }
    )
    result = structured_document(content, set(), profile=canonical(service.db, service.user))
    service.validate_ledger(result, [])
    resume = service.resume(ws.id, content.model_dump())
    review = service.review(ws.id, resume=True, manual_verified=True)
    assert not [i for i in review.data["issues"] if i["code"] == "UNSUPPORTED_METRIC"]
    assert item.source_id in resume.source_ids
    with pytest.raises(ValueError, match="사실 문장"):
        service.validate_ledger({"text": claim["text"], "claims": [{**claim, "type": "METRIC"}]}, [])
    with pytest.raises(ValueError, match="확인된"):
        structured_document(content, set(), profile={})
