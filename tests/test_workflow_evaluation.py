# ruff: noqa: F811 -- reusable workflow fixture
from copy import deepcopy

from career.models import Artifact, Workspace
from career.providers import FakeLLMProvider
from career.workflow_evaluation import workflow_ablation
from sqlalchemy import select
from test_workflow import doc, flow  # noqa: F401


def test_product_ablation_executes_strategy_writer_review_and_partial_patch_in_isolation(flow):
    service, ws, e = flow
    q = service.add_question(ws.id, "실험 경험", 1000)
    before = deepcopy(ws.data)
    original_count = len(list(service.db.scalars(select(Artifact))))
    first = doc(e)
    changed_text = "직접 실험을 설계하고 정확도 80%를 대조했습니다."
    revised = {**first["claims"][0], "text": changed_text}
    fixtures = {
        "benchmark_writer": first,
        "opportunity": {"actual_outputs": ["평가 보고서"], "base_profession": "평가 연구원"},
        "evidence_mapper": {
            "items": [
                {
                    "evidence_id": e.id,
                    "job_output_id": "평가 보고서",
                    "classification": "DIRECT",
                    "evidence_strength": "STRONG",
                    "ownership_strength": "STRONG",
                    "rationale": "평가",
                }
            ],
            "uncovered_outputs": [],
        },
        "strategy": {
            "positioning": "평가 연구원",
            "base_profession_identity": "연구원",
            "main_skill_message": "실험 검증",
            "assignment_statement": "실험 검증",
        },
        "question_brief": {
            "question_id": "will-be-overridden",
            "question_type": "JOB_COMPETENCY",
            "evaluation_intent": "검증",
            "primary_message": "실험 확인",
            "evidence_ids": [e.id],
        },
        "writer": first,
        "fact_reviewer": {"issues": [], "followups": []},
        "recruiter": {"issues": [], "followups": []},
        "reverse_interview": {"issues": [], "followups": []},
        "issue_patch_compression": {
            "old_text": e.body,
            "new_text": changed_text,
            "claims": [revised],
            "issue_codes": ["CLARITY"],
        },
    }

    class ProductProvider(FakeLLMProvider):
        def __init__(self):
            super().__init__(fixtures)
            self.calls = []
            self.review_count = 0

        def structured(self, stage, context, schema):
            self.calls.append(stage)
            if stage == "question_brief":
                return schema.model_validate({**fixtures[stage], "question_id": context["question"]["id"]})
            if stage == "recruiter":
                self.review_count += 1
                if self.review_count == 1:
                    return schema.model_validate(
                        {
                            "issues": [{"priority": "P2", "code": "CLARITY", "message": "결과 표현 정리"}],
                            "followups": [],
                        }
                    )
            return super().structured(stage, context, schema)

    service.provider = ProductProvider()
    result = workflow_ablation(service, ws.id, q["id"])
    assert [row["status"] for row in result["results"]] == ["COMPLETED"] * 4, result
    assert result["results"][2]["revision_count"] == 0
    assert result["results"][3]["revision_count"] == 1
    assert result["results"][3]["draft"]["text"] == changed_text
    assert "issue_patch_compression" in service.provider.calls
    assert "benchmark_patch" not in service.provider.calls
    assert len(list(service.db.scalars(select(Workspace)))) == 1
    assert len(list(service.db.scalars(select(Artifact)))) == original_count
    assert ws.data == before
