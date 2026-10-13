import pytest
from career.references import compile_pack, listing, register
from career.rulebook import compile_sections, overview, sections

COVER = """# Personal writing strategy
# 1. Principles
## 1-1. Derive persona
Build persona from work and evidence.
## 1-4. Decision reasoning
Use necessary decision elements.
# 6. Question design
## 6-2. Recheck facts
Read source, role, metric and limits.
## 6-6. Evidence Test
Test the candidate claim against evidence before approval.
# 7. Drafting
## 7-1. Direct answer
Answer in the opening sentences.
## 7-5. Question structures
### Values
Include repeated choices and current habits.
### Collaboration
Explain a shared goal and concrete coordination.
### Example
I produced 999% revenue.
# 8. Validation
## 8-2. Reverse Test
Ask about alternatives and personal ownership.
# 12. Current Snapshot
I permanently lack all engineering skills.
# 14. Worked Example
I achieved 888%.
"""


def test_current_source_sections_not_static_projection(db):
    first = register(db, "a", "cover", COVER)
    before = compile_pack(db, "a", "writer")["references"][0]
    revised = COVER.replace("Answer in the opening sentences.", "Give the direct answer in two sentences.")
    second = register(db, "a", "cover", revised)
    after = compile_pack(db, "a", "writer")["references"][0]
    assert first.data["content_hash"] != second.data["content_hash"]
    assert before["guidance"] != after["guidance"]
    assert "Give the direct answer in two sentences." in after["guidance"]
    assert "Answer in the opening sentences." not in after["guidance"]
    assert after["compilation_status"] == "SOURCE_SECTIONS"
    assert not after["fact_authority"]


def test_selected_sections_preserve_provenance_and_stage_boundaries():
    question = compile_sections("cover", COVER, "question_brief")
    interview = compile_sections("cover", COVER, "reverse_interview")
    assert any(row["section_number"] == "6-6" for row in question)
    assert any("Values" in row["section"] for row in question)
    assert all(row["chapter"] != "8" for row in question)
    assert any(row["section_number"] == "8-2" for row in interview)
    assert all(row["chapter"] != "7" for row in interview)
    for row in question + interview:
        assert row["rule_id"].startswith("cover:")
        assert COVER.splitlines()[row["start_line"] - 1].startswith("#")
        assert row["end_line"] >= row["start_line"]
        assert row["text"] in COVER


def test_examples_and_personal_snapshot_are_never_compiled_as_requirements(db):
    register(db, "a", "cover", COVER)
    data = compile_pack(db, "a", "writer")["references"][0]
    combined = "\n".join(data["guidance"])
    assert "999%" not in combined and "888%" not in combined
    assert "permanently lack" not in combined
    assert listing(db, "a")[0]["compilation"]["excluded_sections"] > 0
    assert compile_pack(db, "b", "writer")["references"] == []


def test_numbered_source_update_and_nested_templates_are_visible():
    changed = COVER.replace("current habits.", "current habits and a costly choice.")
    values = [s for s in compile_sections("cover", changed, "writer") if "Values" in s["section"]]
    assert len(values) == 1
    assert "costly choice" in values[0]["text"]
    assert overview("cover", changed)["source_backed"]


def test_unknown_reference_format_is_explicit_not_claimed_compiled(db):
    register(db, "a", "cover", "# Fixture\nA new body without mapped headings.")
    compiled = compile_pack(db, "a", "writer")["references"][0]
    assert compiled["compilation_status"] == "DEFAULT_GUIDANCE_ONLY"
    assert compiled["requirements"] == []
    assert listing(db, "a")[0]["compilation"]["status"] == "NEEDS_SECTION_MAPPING"


def test_resume_never_receives_cover_letter_templates(db):
    register(db, "a", "cover", COVER)
    register(db, "a", "resume", "# 7. Bullets\nEach bullet stands alone.")
    packet = compile_pack(db, "a", "recruiter", "RESUME")
    assert {r["key"] for r in packet["references"]} == {"resume"}
    assert packet["references"][0]["guidance"] == ["Each bullet stands alone."]


def test_fenced_headings_do_not_override_actual_section_selection():
    content = "# 6. Question\n\n```\n# 12. Snapshot\nnot a real heading\n```\n# 8. Review\nCheck evidence."
    parsed = sections(content)
    assert len(parsed) == 2 and parsed[0].chapter == "6"
    assert parsed[1].chapter == "8"


REGISTRY = """# Session registry
# 1. Authority
Current corrections outrank derived summaries.
# 6. REFERENCE LAYERS
## 6-A. Expression DB
Expression is style, not fact authority.
## 6-B. Example DB
Past wording never establishes current facts.
### Example
Archived applicant achieved 999%.
# 7. APPLICATION STATE & SNAPSHOT
Application state and submitted content have different roles.
## Submission Snapshot
A frozen copy proves only what was submitted then.
### Snapshot 2024
Archived applicant achieved 888%.
# 8. Learning
An outcome alone cannot establish a causal writing rule.
# 9. Staleness
Recheck affected work after corrections.
# 10. Session scope
Only use the current task's relevant rule pack.
# 11. PACK A — Opportunity
PACK_A_REQUIREMENT
# 12. PACK B — Strategy
PACK_B_REQUIREMENT
# 13. PACK C — Cover
PACK_C_REQUIREMENT
# 14. PACK D — Resume
PACK_D_REQUIREMENT
# 15. PACK E — Fact audit
PACK_E_REQUIREMENT
# 16. PACK F — Interview
PACK_F_REQUIREMENT
# 17. PACK G — Outcome review
PACK_G_REQUIREMENT
# 18. ARCHIVE / SOURCE
Outdated rules must not be injected.
"""


@pytest.mark.parametrize(("stage", "domain", "expected"), [
    ("opportunity", "", "A"), ("evidence_mapper", "", "A"),
    ("opportunity_assessment", "", "A"),
    ("research_source_extract", "", "B"), ("strategy", "", "B"),
    ("question_portfolio", "", "B"),
    ("question_brief", "", "C"), ("claim_evidence_test", "", "C"),
    ("writer", "", "C"), ("recruiter", "", "C"),
    ("submission_readiness", "", "C"), ("issue_patch_compression", "", "C"),
    ("resume_writer", "", "D"), ("recruiter", "RESUME", "D"),
    ("reverse_interview", "RESUME", "D"), ("review_answers", "RESUME", "D"),
    ("review_answer_extract", "RESUME", "D"), ("interview_handoff", "RESUME", "D"),
    ("issue_patch_compression", "RESUME", "D"),
    ("fact_reviewer", "", "E"), ("truth_extraction", "", "E"),
    ("reverse_interview", "", "F"), ("interview_handoff", "", "F"),
    ("postmortem", "", "G"),
])
def test_registry_current_stage_pack_is_source_backed_and_domain_scoped(db, stage, domain, expected):
    register(db, "a", "registry", REGISTRY)
    packet = compile_pack(db, "a", stage, domain)
    reference = packet["references"][0]
    text = "\n".join(reference["guidance"])
    for letter in "ABCDEFG":
        assert (f"PACK_{letter}_REQUIREMENT" in text) == (letter == expected)
    assert "Past wording never establishes current facts." in text
    assert "A frozen copy proves only what was submitted then." in text
    assert "999%" not in text and "888%" not in text and "Outdated rules" not in text
    assert not reference["fact_authority"]
    assert ("An outcome alone" in text) == (expected == "G")
    selected = next(r for r in reference["requirements"] if r["chapter"] == str(11 + "ABCDEFG".index(expected)))
    assert REGISTRY.splitlines()[selected["start_line"] - 1].startswith("#")


def test_registry_pack_source_revision_changes_resume_guidance_and_keeps_cover_out(db):
    register(db, "a", "registry", REGISTRY)
    before = compile_pack(db, "a", "resume_writer")["references"][0]
    register(db, "a", "registry", REGISTRY.replace("PACK_D_REQUIREMENT", "Check exported links and page breaks."))
    after = compile_pack(db, "a", "resume_writer")["references"][0]
    assert before["content_hash"] != after["content_hash"]
    assert "Check exported links and page breaks." in after["guidance"]
    assert "PACK_C_REQUIREMENT" not in "\n".join(after["guidance"])


def test_integrity_source_role_definitions_are_rules_but_nested_examples_stay_excluded():
    content = """# Integrity rules
# 9. Source Role
## Example DB
Old examples are not current truth.
### Example
Someone achieved 777%.
## Submission Snapshot
Use only for the submitted version and interview handoff.
### Snapshot 2020
Someone achieved 666%.
# 10. Privacy
Confirm disclosure scope.
"""
    compiled = compile_sections("integrity", content, "writer")
    text = "\n".join(row["text"] for row in compiled)
    assert "Old examples are not current truth." in text
    assert "Use only for the submitted version" in text
    assert "777%" not in text and "666%" not in text
    assert overview("integrity", content)["excluded_sections"] == 2


def test_similar_snapshot_titles_outside_source_role_chapter_remain_excluded():
    content = "# 7. Writing\n## Submission Snapshot\nPast personal claim.\n# 9. Roles\n## Example DB for applicant\nOld achievement."
    assert compile_sections("integrity", content, "writer") == []


def test_workflow_uses_revised_registry_pack_without_importing_facts_or_logging_content(db):
    from career.models import Evidence, Fact, PromptRun
    from career.schemas import Review
    from career.workflow import Workflow
    from sqlalchemy import select

    captured = []

    class Reviewer:
        def structured(self, stage, context, schema):
            captured.append(context["supplemental_guidance"])
            return schema.model_validate({"issues": [], "followups": []})

    service = Workflow(db, "a", Reviewer())
    service.create("Synthetic", "Analyst", "Prepare reports.")
    register(db, "a", "registry", REGISTRY)
    service.ai("recruiter", {"document_domain": "RESUME"}, Review)
    changed = register(db, "a", "registry", REGISTRY.replace("PACK_D_REQUIREMENT", "Recheck the current resume file."))
    service.ai("recruiter", {"document_domain": "RESUME"}, Review)
    assert "PACK_D_REQUIREMENT" in captured[0]["references"][0]["guidance"]
    assert "Recheck the current resume file." in captured[1]["references"][0]["guidance"]
    assert all(packet["pack"] == "resume" for packet in captured)
    assert compile_pack(db, "another-owner", "recruiter", "RESUME")["references"] == []
    traces = list(db.scalars(select(PromptRun).order_by(PromptRun.created_at)))
    assert len(traces) == 2
    assert traces[0].data["input_hash"] != traces[1].data["input_hash"]
    assert traces[1].data["reference_versions"][0]["content_hash"] == changed.data["content_hash"]
    assert all("Recheck the current resume file." not in str(trace.data) for trace in traces)
    assert not list(db.scalars(select(Evidence))) and not list(db.scalars(select(Fact)))
