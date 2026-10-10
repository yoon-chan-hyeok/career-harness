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
