import pytest
from career.resume import ResumeContent
from career.resume_layout import ORDER, arrange, rank_evidence, section_budgets


def items():
    base = {
        "job_output_id": "Report",
        "classification": "DIRECT",
        "evidence_strength": "STRONG",
        "ownership_strength": "STRONG",
        "rationale": "report",
    }
    return [
        {**base, "evidence_id": "diff", "skill_focus": "DIFFERENTIATOR", "skill_name": "Automation"},
        {**base, "evidence_id": "main", "skill_focus": "MAIN_SKILL", "skill_name": "Analysis"},
    ]


def test_main_skill_is_ranked_before_differentiator_and_provenance_is_checked():
    opportunity = {
        "main_skills": ["Analysis"],
        "differentiators": ["Automation"],
        "output_importance": [{"output": "Report", "importance": "CRITICAL"}],
    }
    evidence = [{"id": "diff", "body": "report", "data": {}}, {"id": "main", "body": "analysis", "data": {}}]
    result = rank_evidence(opportunity, items(), evidence)
    assert [i["evidence_id"] for i in result] == ["main", "diff"]
    assert result[0]["output_importance"] == "CRITICAL"
    assert result[0]["recency_date"] is None
    with pytest.raises(ValueError, match="현재 직무"):
        rank_evidence(opportunity, [{**items()[0], "skill_name": "Invented"}], evidence)
    with pytest.raises(ValueError, match="원문"):
        rank_evidence(opportunity, [{**items()[0], "concrete_output": "Imagined output"}], evidence)


def test_section_order_and_bullet_priority_follow_brief_but_user_order_is_preserved():
    def bullet(ident):
        return {
            "text": "Performed analysis " + ident,
            "evidence_ids": [ident],
            "claims": [
                {
                    "text": "Performed analysis " + ident,
                    "evidence_ids": [ident],
                    "type": "FACT",
                    "support": "SUPPORTED",
                    "ownership_ok": True,
                }
            ],
        }

    content = ResumeContent.model_validate(
        {
            "sections": [
                {"title": "Skills", "kind": "SKILLS", "bullets": [bullet("diff")]},
                {"title": "Projects", "kind": "PROJECT", "bullets": [bullet("diff"), bullet("main")]},
            ]
        }
    )
    brief = {
        "section_order": ORDER,
        "section_budget": section_budgets(1),
        "selected_evidence_ids": ["main", "diff"],
    }
    value = arrange(content, brief)
    assert value.sections[0].kind == "PROJECT"
    assert value.sections[0].bullets[0].evidence_ids == ["main"]
    assert arrange(content, brief, preserve_order=True).model_dump() == content.model_dump()
    brief["section_budget"]["PROJECT"]["max_characters"] = 5
    with pytest.raises(ValueError, match="초과"):
        arrange(content, brief)
