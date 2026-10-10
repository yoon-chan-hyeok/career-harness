"""Compile stage-specific rule excerpts from user-owned Markdown references.

Source text remains untrusted domain data. No examples become facts; application
code alone owns permissions, approvals, source validation and state transitions.
"""
import hashlib
import re
from dataclasses import dataclass

COMPILER_VERSION = "rule-sections-v1"

# Rule domains intentionally exclude personal snapshots, project Fact Locks,
# archived workflows and worked examples. Expression exemplars have a separate,
# evidence-bound selection path; they are not instructions or candidate facts.
ALLOWED = {
    "registry": {"1", "8", "9", "10"},
    "integrity": {str(n) for n in range(12)},
    "opportunity": {"0", *map(str, range(2, 12)), "13", "14", "15"},
    "cover": {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "13", "17"},
    "resume": {str(n) for n in range(22)} - {"17"},
    "expression": {"0", "1", "8", "9", "10"},
}
COVER_SECTIONS = {
    "research": {"0", "1-1", "1-2", "2"},
    "research_plan": {"0", "1-1", "1-2", "2"},
    "research_extract": {"0", "1-1", "1-2", "2"},
    "research_source_extract": {"0", "1-1", "1-2", "2"},
    "web_search": {"0", "1-1", "1-2", "2"},
    "strategy": {"1", "3", "4", "5"},
    "question_portfolio": {"1-1", "1-3", "5"},
    "question_brief": {"1-4", "4-4", "4-5", "5", "6", "7-5"},
    "claim_evidence_test": {"1-2", "4-1", "4-3", "4-4", "4-5", "6", "8-1", "13"},
    "writer": {"1-3", "1-4", "6-4", "6-6", "6-7", "7", "13"},
    "recruiter": {"1-2", "1-3", "3-4", "5-4", "7", "8-3", "8-4", "17"},
    "reverse_interview": {"3-4", "8-1", "8-2", "8-3", "8-4", "13", "17"},
    "review_answers": {"3-4", "8", "13", "17"},
    "review_answer_extract": {"8-2", "8-3", "13"},
    "interview_handoff": {"8-1", "8-2", "8-3", "13", "17"},
    "issue_patch_compression": {"1-4", "7", "8-5", "8-6", "13"},
    "submission_readiness": {"8", "17"},
}
REGISTRY_SECTIONS = {
    "postmortem": {"1", "8", "9"},
    "truth_extraction": {"1", "9"},
}
_HEADER = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_NUMBER = re.compile(r"^(\d+(?:-[\dA-Z]+)?)(?:[.\s]|$)")
_EXCLUDED = re.compile(r"예시|\bexample\b|\bfact\s*lock\b|snapshot|스냅샷|archive|아카이브", re.I)


@dataclass(frozen=True)
class Section:
    title: str
    path: tuple[str, ...]
    number: str
    chapter: str
    start_line: int
    end_line: int
    text: str
    excluded: bool

    def view(self, key: str):
        identity = hashlib.sha256("/".join(self.path).encode()).hexdigest()[:10]
        return {
            "rule_id": f"{key}:{self.number or self.chapter}:{identity}",
            "section": " / ".join(self.path),
            "section_number": self.number,
            "chapter": self.chapter,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "text": self.text,
            "role": "DOMAIN_REQUIREMENT_NOT_FACT_OR_SYSTEM_INSTRUCTION",
        }


def sections(content: str) -> list[Section]:
    """Preserve exact local section content/line provenance, not an LLM summary."""
    lines = content.splitlines()
    stack: list[tuple[int, str, str]] = []
    result = []
    body: list[str] = []
    current: tuple[tuple[str, ...], str, str, int, bool] | None = None
    fenced = False

    def flush(end: int):
        if current is None:
            return
        text = "\n".join(body).strip()
        if text and any(line.strip() not in {"", "---"} for line in body):
            path, number, chapter, start, excluded = current
            result.append(Section(path[-1], path, number, chapter, start, end, text, excluded))

    for index, line in enumerate(lines, 1):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        match = _HEADER.match(line) if not fenced else None
        if match is None:
            if current is not None:
                body.append(line)
            continue
        flush(index - 1)
        level, title = len(match[1]), match[2]
        while stack and stack[-1][0] >= level:
            stack.pop()
        number_match = _NUMBER.match(title)
        number = number_match[1] if number_match else next((n for _, _, n in reversed(stack) if n), "")
        stack.append((level, title, number))
        path = tuple(t for _, t, _ in stack)
        chapter = number.split("-")[0]
        current = (path, number, chapter, index, any(_EXCLUDED.search(t) for t in path))
        body = []
    flush(len(lines))
    return result


def _matches(number: str, selected: set[str]) -> bool:
    return any(number == value or number.startswith(value + "-") for value in selected)


def selected_sections(key: str, content: str, stage: str):
    allowed = ALLOWED.get(key, set())
    selected = COVER_SECTIONS.get(stage, ALLOWED["cover"]) if key == "cover" else (
        REGISTRY_SECTIONS.get(stage, {"1", "9", "10"}) if key == "registry" else allowed
    )
    return [
        section for section in sections(content)
        if section.chapter in allowed and not section.excluded and _matches(section.number, selected)
    ]


def compile_sections(key: str, content: str, stage: str):
    return [section.view(key) for section in selected_sections(key, content, stage)]


def overview(key: str, content: str):
    parsed = sections(content)
    applicable = [s for s in parsed if s.chapter in ALLOWED.get(key, set()) and not s.excluded]
    return {
        "compiler_version": COMPILER_VERSION,
        "status": "SOURCE_SECTIONS" if applicable else "NEEDS_SECTION_MAPPING",
        "requirement_sections": len(applicable),
        "excluded_sections": sum(s.excluded or s.chapter not in ALLOWED.get(key, set()) for s in parsed),
        "source_backed": bool(applicable),
        "notice": "원문에서 단계별 규칙을 선택합니다. 예시·개인 스냅샷은 사실로 등록하지 않습니다."
        if applicable else "원문의 절 번호를 확인해 주세요. 기본 일반 지침만 적용 중입니다.",
    }
