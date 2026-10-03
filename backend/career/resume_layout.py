"""Job-based evidence priority and measured section budgets for resume drafting."""

from copy import deepcopy
from datetime import date

from career.schemas import RESUME_CHARACTER_BUDGET

STRENGTH = {"STRONG": 0, "MODERATE": 1, "LIMITED": 2, "NONE": 3}
IMPORTANCE = {"CRITICAL": 0, "CORE": 1, "SUPPORTING": 2, "UNSPECIFIED": 3}
FOCUS = {"MAIN_SKILL": 0, "UNSPECIFIED": 1, "DIFFERENTIATOR": 2}
ORDER = ["SUMMARY", "PROJECT", "EXPERIENCE", "EDUCATION", "SKILLS"]
WEIGHTS = {"SUMMARY": 10, "PROJECT": 40, "EXPERIENCE": 28, "EDUCATION": 13, "SKILLS": 9}


def rank_evidence(opportunity, items, evidence):
    importance = {i["output"]: i["importance"] for i in opportunity.get("output_importance", [])}
    by_id = {e["id"]: e for e in evidence}
    grouped = {}
    for item in items:
        if item["classification"] == "NO_EVIDENCE":
            continue
        focus = item.get("skill_focus", "UNSPECIFIED")
        name = item.get("skill_name", "")
        if focus != "UNSPECIFIED" and name not in opportunity.get(
            "main_skills" if focus == "MAIN_SKILL" else "differentiators", []
        ):
            raise ValueError("핵심 역량·차별점은 현재 직무 분석의 항목과 연결해 주세요.")
        e = by_id[item["evidence_id"]]
        for key in ("concrete_output", "understandable_hook"):
            quote = item.get(key, "")
            if quote and quote not in e["body"] and quote not in e.get("data", {}).get("output", ""):
                raise ValueError("산출물과 설명 단서는 선택한 근거의 원문과 대조해 주세요.")
        grouped.setdefault(item["evidence_id"], []).append(item)

    def score(item):
        return (
            FOCUS[item.get("skill_focus", "UNSPECIFIED")],
            item["classification"] != "DIRECT",
            IMPORTANCE[importance.get(item["job_output_id"], "UNSPECIFIED")],
            STRENGTH[item["evidence_strength"]],
            STRENGTH[item["ownership_strength"]],
            not bool(item.get("concrete_output")),
            not bool(item.get("understandable_hook")),
        )

    ranked = []
    for evidence_id, relations in grouped.items():
        best = min(relations, key=score)
        raw_date = by_id[evidence_id].get("data", {}).get("verified_at", "")
        try:
            recency = date.fromisoformat(raw_date[:10]) if isinstance(raw_date, str) and raw_date else None
        except ValueError:
            recency = None
        ranked.append(
            (
                score(best),
                -(recency.toordinal() if recency else 0),
                evidence_id,
                {
                    "rank": 1,
                    "evidence_id": evidence_id,
                    "skill_focus": best.get("skill_focus", "UNSPECIFIED"),
                    "skill_name": best.get("skill_name", ""),
                    "job_output_ids": list(dict.fromkeys(i["job_output_id"] for i in relations)),
                    "output_importance": importance.get(best["job_output_id"], "UNSPECIFIED"),
                    "classification": best["classification"],
                    "evidence_strength": best["evidence_strength"],
                    "ownership_strength": best["ownership_strength"],
                    "concrete_output": best.get("concrete_output", ""),
                    "understandable_hook": best.get("understandable_hook", ""),
                    "recency_date": recency.isoformat() if recency else None,
                    "rationale": best["rationale"],
                },
            )
        )
    ranked.sort(key=lambda row: row[:3])
    return [{**row[3], "rank": index + 1} for index, row in enumerate(ranked)]


def section_budgets(page_budget):
    total = RESUME_CHARACTER_BUDGET[page_budget]
    return {
        kind: {
            "max_characters": total * weight // 100,
            "max_bullets": 4 if kind in {"SUMMARY", "SKILLS"} else 16,
        }
        for kind, weight in WEIGHTS.items()
    }


def arrange(content, brief, *, preserve_order=False):
    from career.resume import ResumeContent

    value = deepcopy(content.model_dump())
    order = {key: index for index, key in enumerate(brief["section_order"])}
    rank = {key: index for index, key in enumerate(brief["selected_evidence_ids"])}
    if len({s["kind"] for s in value["sections"]}) != len(value["sections"]):
        raise ValueError("같은 종류의 이력서 섹션을 한 곳에 정리해 주세요.")
    if not preserve_order:
        value["sections"].sort(key=lambda s: order.get(s["kind"], len(order)))
    for section in value["sections"]:
        if not preserve_order:
            section["bullets"].sort(
                key=lambda b: min([rank[i] for i in b["evidence_ids"] if i in rank] or [len(rank)])
            )
        budget = brief["section_budget"].get(section["kind"])
        if not budget:
            raise ValueError("이력서 섹션의 순서와 분량 예산을 지정해 주세요.")
        actual = len(
            "## " + section["title"] + "\n" + "\n".join("- " + b["text"] for b in section["bullets"])
        )
        if actual > budget["max_characters"] or len(section["bullets"]) > budget["max_bullets"]:
            raise ValueError("이력서 섹션의 문자·항목 예산을 초과했습니다: " + section["title"])
    return ResumeContent.model_validate(value)
