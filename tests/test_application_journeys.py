"""Whole synthetic HTTP journeys. Fixture responses prove routing, not AI quality."""
# ruff: noqa: F811 -- shared isolated HTTP fixture
from copy import deepcopy

import pytest
from career.api import app, database
from career.claim_test import CHECKS
from career.references import register
from test_api import client  # noqa: F401
from test_rulebook import REGISTRY

SCENARIOS = {
    "hybrid": {"role": "업무 분석가", "outputs": ["업무 보고서", "인수인계 기준"],
               "main": "업무 분석", "diff": "분석 자동화", "pages": 2,
               "facts": ["현업 요청을 분류하고 예외 처리 기준을 보고서로 정리했습니다.",
                         "팀과 검토 순서를 합의하고 인수인계 기준을 문서로 남겼습니다."]},
    "technical": {"role": "소프트웨어 개발자", "outputs": ["검증 API", "운영 절차"],
                  "main": "API 구현", "diff": "모델 평가", "pages": 1,
                  "facts": ["입력 검증 API를 구현하고 오류 응답을 확인했습니다.",
                            "팀과 장애 대응 순서를 합의하고 운영 절차를 문서로 남겼습니다."]},
}


def claims(text, evidence_id):
    return [{"text": text, "type": "FACT", "evidence_ids": [evidence_id],
             "support": "SUPPORTED", "ownership_ok": True}]


class JourneyProvider:
    """Bounded prerecorded synthetic responses, with dynamic fixture IDs only."""
    last_trace = {"model": "synthetic-journey-not-live-ai"}

    def __init__(self, case):
        self.case = case
        self.evidence = []
        self.calls = []
        self.mapping = "DIRECT"

    def structured(self, stage, context, schema):
        self.calls.append((stage, deepcopy(context)))
        case = self.case
        clean_review = {"issues": [], "followups": []}
        if stage == "opportunity":
            data = {"base_profession": case["role"], "actual_outputs": case["outputs"],
                    "main_skills": [case["main"]], "differentiators": [case["diff"]],
                    "output_importance": [{"output": output, "importance": "CORE"} for output in case["outputs"]],
                    "required": [{"requirement": "학사", "source_id": "jd"}], "posting_status": "OPEN"}
        elif stage == "evidence_mapper":
            data = {"items": [{"evidence_id": e["id"], "job_output_id": output,
                     "classification": self.mapping, "evidence_strength": "STRONG", "ownership_strength": "STRONG",
                     "rationale": "합성 기록의 수행 업무와 산출물 대조", "skill_focus": "MAIN_SKILL",
                     "skill_name": case["main"], "concrete_output": e["body"]}
                    for e, output in zip(self.evidence, case["outputs"], strict=True)], "uncovered_outputs": []}
        elif stage == "opportunity_assessment":
            data = {"eligibility": [{"requirement": "학사", "status": "MET", "reason": "등록 학력 확인",
                                      "profile_keys": ["profile:degree"]}],
                    **{key: {"level": "MEDIUM", "reason": "현재 공고와 확인 자료를 대조함", "source_ids": ["jd"]}
                       for key in ("fit", "career_value", "action_priority")},
                    "selection_risks": ["실제 운영 범위는 별도 확인 필요"], "preparation_cost": "SHORT",
                    "recommendation": "PROCEED_WITH_GAP", "main_fix": "업무 수행 범위를 구분한다"}
        elif stage == "strategy":
            data = {"positioning": case["role"], "base_profession_identity": case["role"],
                    "main_skill_message": case["main"], "differentiator_message": case["diff"],
                    "assignment_statement": case["outputs"][0] + " 작성과 근거 확인을 맡길 수 있습니다.",
                    "fatal_gap_strategy": "운영 규모에 관한 미확인 주장은 쓰지 않습니다."}
        elif stage == "question_portfolio":
            data = {"items": [{"question_id": q["id"], "evaluation_intent": q["text"],
                     "identity_role": role, "primary_message_candidates": [e["body"]],
                     "evidence_candidate_ids": [e["id"]], "avoided_repetition": ["다른 문항의 동일 사실"]}
                    for q, e, role in zip(context["questions"], self.evidence, ["실무 수행", "협업 조율"], strict=True)]}
        elif stage == "question_brief":
            collaboration = "협업" in context["question"]["text"]
            e = self.evidence[int(collaboration)]
            data = {"question_id": context["question_id"],
                    "question_type": "COLLABORATION" if collaboration else "JOB_COMPETENCY",
                    "evaluation_intent": "합의 과정" if collaboration else "업무 수행 범위",
                    "primary_message": e["body"], "evidence_ids": [e["id"]],
                    "decision": "반복되는 판단을 문서로 정리하기로 했습니다.",
                    "operational_value": "후속 검토에서 같은 기준을 참고할 수 있습니다.",
                    "value_scope": "OPERATIONAL_POSSIBILITY", "job_relevance": case["outputs"][int(collaboration)]}
        elif stage == "claim_evidence_test":
            e = context["evidence"][0]
            data = {"claims": [{"claim": context["brief"]["primary_message"], "support": "SUPPORTED",
                                "rationale": "합성 원문에서 직접 대조함",
                                "citations": [{"evidence_id": e["id"], "quote": e["body"]}]}],
                    "checks": [{"key": key, "verdict": "PASS", "rationale": "합성 원문 수행 범위와 대조함"}
                               for key in CHECKS], "followups": []}
        elif stage == "writer":
            e = context["evidence"][0]
            data = {"text": e["body"], "claims": claims(e["body"], e["id"])}
        elif stage == "resume_writer":
            data = {"sections": [{"title": "프로젝트", "kind": "PROJECT",
                    "bullets": [{"text": e["body"], "evidence_ids": [e["id"]],
                                 "claims": claims(e["body"], e["id"])} for e in self.evidence]}]}
        elif stage == "reverse_interview":
            question = "본인이 수행한 범위와 팀의 역할을 구분해 주세요."
            data = {**clean_review, "followups": [question],
                    "followup_details": [{"question": question, "category": "GROUNDING"}]}
        elif stage in {"fact_reviewer", "recruiter", "cross_document_consistency"}:
            data = clean_review
        elif stage == "issue_patch_compression":
            before = context["document"]["text"]
            after = before.replace(" 그리고 매우 중요한 경험입니다.", "")
            data = {"old_text": before, "new_text": after,
                    "claims": claims(after, context["evidence"][0]["id"]), "issue_codes": ["CHAR_LIMIT"]}
        else:
            raise AssertionError("Unexpected AI stage: " + stage)
        return schema.model_validate(data)


class Journey:
    def __init__(self, client, case):
        self.client, self.case = client, case
        self.counter = 0
        self.evidence = []
        client.headers["Authorization"] = "Bearer alice-key"
        workspace = self.post("/api/applications", {"company": "가상 인수 회사", "role": case["role"],
                              "jd_raw": "학사. " + ", ".join(case["outputs"]) + " 담당자를 채용합니다."})
        self.path = "/api/applications/" + workspace["id"]

    def post(self, path, body):
        response = self.client.post(path, json=body)
        assert response.status_code == 200, (path, response.text)
        return response.json()

    def act(self, action, **body):
        return self.post(self.path + "/actions/" + action, body)

    def state(self):
        response = self.client.get(self.path)
        assert response.status_code == 200
        return response.json()

    def current(self, kind, qid=""):
        return max((a for a in self.state()["artifacts"] if a["kind"] == kind and a["slot"] == qid),
                   key=lambda a: a["version"])

    def say(self, text="ㄱㄱ", qid="", artifact_id="", expected="OK"):
        self.counter += 1
        data = self.post(self.path + "/conversation", {"text": text, "question_id": qid,
                         "artifact_id": artifact_id, "client_id": f"journey-message-{self.counter}"})
        result = data["data"]["response"]
        assert result["status"] == expected, result
        return result

    def review_answer_lock(self, qid="", resume=False):
        review = self.act("review", qid=qid, resume=resume)
        document = self.current("ResumeContent" if resume else "Draft", qid)
        blocked = self.client.post(self.path + "/actions/final-lock", json={"qid": qid, "resume": resume})
        assert blocked.status_code == 409
        assert "검수 질문" in blocked.text or "이전 근거" in blocked.text
        e = next(e for e in self.evidence if e["id"] in document["data"]["selected_evidence_ids"])
        self.act("review-answers", qid=qid, resume=resume, manual_verified=True,
                 responses={"review_id": review["id"], "review_version": review["version"], "confirmed": True,
                            "entries": [{"task_id": task["id"], "action": "ANSWER_WITH_EVIDENCE",
                                         "answer": e["body"], "rationale": "등록한 수행 기록을 직접 확인함",
                                         "citations": [{"evidence_id": e["id"], "quote": e["body"]}]}
                                        for task in review["data"]["response_tasks"]]})
        if resume:
            preview = self.client.get(self.path + "/resume/preview")
            assert preview.status_code == 200 and "프로젝트" in preview.text
            self.post(self.path + "/resume/file-qa", {"artifact_id": document["id"], "confirmed": True})
        self.act("final-lock", qid=qid, resume=resume, artifact_id=document["id"])


@pytest.mark.parametrize("scenario", ["hybrid", "technical"])
def test_http_complete_application_with_mapping_correction_resume_and_immutable_handoff(client, monkeypatch, scenario):
    case = SCENARIOS[scenario]
    provider = JourneyProvider(case)
    monkeypatch.setattr("career.workflow.configured_provider", lambda: provider)
    monkeypatch.setattr("career.parallel_qa.configured_provider", lambda: provider)
    monkeypatch.setattr("career.portfolio_review.provider_available", lambda: True)
    journey = Journey(client, case)

    # Only reference registration uses setup access; all candidate inputs,
    # approvals, corrections, writing and submission actions cross HTTP boundaries.
    generator = app.dependency_overrides[database]()
    db = next(generator)
    references = {"registry": REGISTRY, "integrity": "# 1. Truth\nCurrent evidence before wording.",
                  "opportunity": "# 3. Eligibility\nCheck every required condition.",
                  "resume": "# 20. File QA\nReview the actual exported document.",
                  "cover": "# 5. Portfolio\n## 5-4. Repetition\n금지: 같은 Fact, 같은 숫자, 같은 결론, 같은 메시지의 반복.",
                  "expression": "# 1. Value\nSeparate operational possibility from measured results."}
    for key, content in references.items():
        register(db, "alice", key, content)
    db.commit()
    generator.close()
    journey.evidence = [journey.post("/api/evidence", {"title": output, "body": fact,
                       "source_title": "합성 수행 기록 " + output, "ownership": "USER", "confirmed": True})
                        for output, fact in zip(case["outputs"], case["facts"], strict=True)]
    provider.evidence = journey.evidence
    journey.post("/api/corrections", {"key": "degree", "value": {"text": "가상 대학교 학사"}})

    research = journey.act("research-source", method="PASTE", category="COMPANY", freshness="CURRENT",
                           title="가상 회사 소개", text="기업 고객을 위한 분석과 소프트웨어 서비스를 제공합니다.")
    company_id = research["data"]["sources"][0]["id"]
    research = journey.act("research-source", research_id=research["id"], method="PASTE", category="HISTORICAL_JD",
                           title="가상 과거 공고", text="과거에는 보고서 검토와 협업 업무를 담당했습니다.")
    historical_id = research["data"]["sources"][-1]["id"]
    proof = {"source_id": company_id, "quote": "분석과 소프트웨어 서비스를 제공합니다."}
    research = journey.act("research-extract", research_id=research["id"], manual={
        "company_facts": [{"statement": "기업 대상 분석과 소프트웨어 서비스", "citation": proof}],
        "historical_jd_signals": [{"statement": "과거의 협업 업무", "citation": {
            "source_id": historical_id, "quote": "보고서 검토와 협업 업무를 담당했습니다."}}],
        "inferences": [{"text": "서비스의 산출물을 담당할 인력이 필요할 수 있습니다.", "citations": [proof]}]})
    blocked = client.post(journey.path + "/actions/analyze", json={})
    assert blocked.status_code == 409 and "채용 배경" in blocked.text
    journey.act("research-confirm", research_id=research["id"], mode="HYPOTHESIS", confirmed=True,
                hypothesis="서비스의 산출물을 담당할 인력이 필요할 수 있습니다.", citations=[proof],
                limitation="실제 내부 인력 충원 사유는 공개 자료만으로 알 수 없습니다.")
    for kind in ("OpportunityBrief", "EvidencePack", "OpportunityAssessment", "ApplicationBrief"):
        journey.say()
        assert journey.current(kind)["status"] == "ACTIVE"
    assert journey.state()["state"] == "WAITING_STRATEGY_APPROVAL"
    journey.say("이걸로 가자")
    questions = [journey.act("add-question", text=text, limit=1000) for text in ("직무 역량", "협업 과정")]

    def write_questions(previous=None):
        journey.say(qid=questions[0]["id"])
        allocation = journey.current("QuestionPortfolio")
        journey.say("이걸로 가자", artifact_id=allocation["id"])
        for index, question in enumerate(questions):
            qid = question["id"]
            journey.say(qid=qid)  # current QuestionBrief
            journey.say(qid=qid)  # Evidence Test
            assert journey.current("ClaimEvidenceTest", qid)["data"]["result"] == "PASSED"
            assert journey.current("QuestionBrief", qid)["status"] == "ACTIVE"
            journey.say("이걸로 가자", qid)
            journey.say(qid=qid, artifact_id=previous[index]["id"] if previous else "")
            journey.review_answer_lock(qid)

    write_questions()
    first_drafts = [journey.current("Draft", q["id"]) for q in questions]
    first_resume = journey.act("resume", page_budget=case["pages"])
    journey.review_answer_lock(resume=True)
    # A user correction invalidates dependent work. Normal Next must recover
    # through new approval gates while retaining the previous versions.
    journey.act("commands", text="이건 Adjacent", evidence_id=journey.evidence[0]["id"])
    provider.mapping = "ADJACENT"
    assert all(journey.current("Draft", q["id"])["status"] == "STALE" for q in questions)
    assert journey.current("ResumeContent")["status"] == "STALE"
    journey.say()  # new assessment
    journey.say()  # new strategy
    journey.say("이걸로 가자")
    write_questions(first_drafts)
    assert all(journey.current("Draft", q["id"])["version"] == old["version"] + 1
               for q, old in zip(questions, first_drafts, strict=True))
    old_selection = journey.say("다시", questions[0]["id"], first_drafts[0]["id"], expected="NEEDS_INPUT")
    assert "이전 버전" in old_selection["text"]
    journey.say(artifact_id=first_resume["id"])
    resume = journey.current("ResumeContent")
    assert resume["data"]["page_budget"] == case["pages"]
    journey.review_answer_lock(resume=True)

    # A real partial edit creates an over-budget document. The model's proposal
    # cannot alter it until accepted, and old review answers never approve it.
    qid = questions[0]["id"]
    draft = journey.current("Draft", qid)
    extended = draft["data"]["text"] + " 그리고 매우 중요한 경험입니다." * 80
    journey.act("patch", qid=qid, old_text=draft["data"]["text"], new_text=extended)
    journey.act("ledger", qid=qid, claims=claims(extended, journey.evidence[0]["id"]))
    review = journey.act("review", qid=qid)
    assert any(issue["code"] == "CHAR_LIMIT" for issue in review["data"]["issues"])
    before_proposal = journey.current("Draft", qid)
    proposal = journey.act("revise", qid=qid)
    assert journey.current("Draft", qid)["id"] == before_proposal["id"]
    assert client.post(journey.path + "/actions/final-lock", json={"qid": qid}).status_code == 409
    journey.post(journey.path + "/revision-proposals/" + proposal["id"], {"decision": "ACCEPT"})
    assert journey.current("Draft", qid)["data"]["text"] == draft["data"]["text"]
    assert journey.current("Review", qid)["status"] == "STALE"
    journey.review_answer_lock(qid)
    # Independent reader gets no private proof; evidence reviewer receives it.
    for stage, context in provider.calls:
        if stage == "recruiter":
            assert not {"evidence", "strategy", "canonical_profile"}.intersection(context)
        if stage in {"writer", "resume_writer", "fact_reviewer"}:
            assert context["evidence"]

    final_context = client.get(journey.path + "/final-review-context").json()
    journey.act("final-review", context_hash=final_context["context_hash"], role_noun=case["role"],
                role_alignment="MATCH", assignment_answer=case["outputs"][0] + " 작성과 결과 확인을 담당할 수 있습니다.",
                motivation_answer="저는 이 직무의 본업을 배우고 관련 산출물을 직접 만드는 일을 하고 싶습니다.",
                wants_core_work=True, evidence_answer="등록한 수행 기록의 산출물과 협업 과정이 이 업무에 연결됩니다.",
                gaps_answer="대규모 실서비스 운영 경험을 증명한 것은 아닙니다.", decision="PASS", return_stage="NONE",
                confirmed=True, citations=[{"evidence_id": journey.evidence[0]["id"], "quote": case["facts"][0]}])
    whole = journey.act("portfolio-review")
    assert whole["data"]["complete"] and whole["data"]["result"] == "PASSED"
    journey.act("ready")
    bundle = journey.act("freeze")
    assert journey.state()["state"] == "SUBMISSION_FROZEN" and bundle["data"]["submitted_at"] is None
    assert len(bundle["data"]["cover_letter_answers"]) == 2
    assert bundle["data"]["resume_version"] == resume["version"]
    snapshot = deepcopy(bundle["data"])
    handoff = journey.act("interview-handoff")
    assert len(handoff["data"]["review_responses"]) == 3
    assert journey.current("SubmissionBundle")["data"] == snapshot
    assert client.post(journey.path + "/actions/confirm", json={"confirmed": False}).status_code == 409
    journey.act("confirm", confirmed=True)
    assert journey.state()["state"] == "SUBMITTED"
    assert journey.current("SubmissionBundle")["data"] == snapshot
    client.headers["Authorization"] = "Bearer bob-key"
    assert client.get(journey.path).status_code == 404
    assert client.get(journey.path + "/submission").status_code == 404
