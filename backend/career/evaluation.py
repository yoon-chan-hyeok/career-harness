from difflib import SequenceMatcher
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from career.models import Feedback, PromptRun, Revision
from career.schemas import Document, Review
from career.validation import hard_qa


class HistoricalJudgment(BaseModel):
    rejected: bool
    reason: str


def historical_smoke(provider, cases: list[dict]):
    results = []
    for case in cases:
        bad = provider.structured(
            "historical_guard",
            {
                "input": case["input"],
                "candidate": case["bad_behavior"],
                "criterion": case["expected_behavior"],
            },
            HistoricalJudgment,
        )
        good = provider.structured(
            "historical_guard",
            {
                "input": case["input"],
                "candidate": case["expected_behavior"],
                "criterion": case["expected_behavior"],
            },
            HistoricalJudgment,
        )
        results.append(
            {
                "id": case["id"],
                "target": case["target"],
                "bad_rejected": bad.rejected,
                "expected_accepted": not good.rejected,
                "pass": bad.rejected and not good.rejected,
            }
        )
    return {
        "cases": results,
        "passed": sum(r["pass"] for r in results),
        "total": len(results),
        "label": "MODEL_JUDGED_SMOKE_NOT_HUMAN_VALIDATION",
    }


def production_metrics(db: Session, user: str):
    feedback = list(db.scalars(select(Feedback).where(Feedback.user_id == user)))
    revisions = list(db.scalars(select(Revision).where(Revision.user_id == user)))
    edits = [r.data["edit_distance_ratio"] for r in revisions]
    finals = [e for e in feedback if "final_user_edit_distance" in e.data]
    maps = [e for e in feedback if e.stage == "EvidencePack" and e.action == "EDIT"]
    replacements = []
    for event in maps:
        before = {i["evidence_id"] for i in (event.data.get("before") or {}).get("items", [])}
        after = {i["evidence_id"] for i in (event.data.get("after") or {}).get("items", [])}
        replacements.append(len(before ^ after) / len(before | after) if before | after else 0.0)
    traces = list(db.scalars(select(PromptRun).where(PromptRun.user_id == user)))
    costs: dict[str, list[float]] = {}
    for trace in traces:
        if trace.data.get("workspace_id") and isinstance(trace.data.get("cost"), (int, float)):
            costs.setdefault(trace.data["workspace_id"], []).append(trace.data["cost"])
    return {
        "decisions": len(feedback),
        "acceptance_rate": sum(e.action == "ACCEPT" for e in feedback) / len(feedback) if feedback else None,
        "mean_revision_distance": sum(edits) / len(edits) if edits else None,
        "final_user_edit_distance": sum(e.data["final_user_edit_distance"] for e in finals) / len(finals)
        if finals
        else None,
        "first_draft_acceptance": sum(e.data["first_draft_accepted"] for e in finals) / len(finals)
        if finals
        else None,
        "revision_count": len(revisions),
        "evidence_replacement_rate": sum(replacements) / len(replacements) if replacements else None,
        "mean_seconds_to_final": sum(
            e.data["seconds_to_final"] for e in finals if "seconds_to_final" in e.data
        )
        / len([e for e in finals if "seconds_to_final" in e.data])
        if any("seconds_to_final" in e.data for e in finals)
        else None,
        "cost_per_application": {k: sum(values) for k, values in costs.items()},
        "cost_coverage": "UNAVAILABLE" if not costs else "ONLY_RECORDED_PROVIDER_COSTS",
        "conclusion": "INSUFFICIENT_DATA" if not feedback else "DESCRIPTIVE_ONLY_NOT_CAUSAL",
    }


def reviewer_metrics(labels: list[dict]):
    valid = [label for label in labels if label.get("valid") is not None]
    accepted = [label for label in labels if label.get("accepted") is not None]
    return {
        "issue_precision": sum(bool(label["valid"]) for label in valid) / len(valid) if valid else None,
        "suggestion_acceptance": sum(bool(label["accepted"]) for label in accepted) / len(accepted)
        if accepted
        else None,
        "label_count": len(labels),
    }


def benchmark(provider, case: dict[str, Any], systems=("B0", "B1", "B2", "B3")):
    """Run controlled ablations on the same input. Caller supplies consented eval data."""
    results = []
    for system in systems:
        if system not in {"B0", "B1", "B2", "B3"}:
            raise ValueError("Unknown baseline")
        context = {"jd": case["jd"], "question": case["question"]}
        if system == "B0":
            context["broad_context"] = case.get("broad_context", {})
        else:
            context["selected_evidence"] = case["evidence"]
        if system in {"B2", "B3"}:
            context["strategy"] = case["strategy"]
        draft = provider.structured("benchmark_writer", context, Document).model_dump()
        reviewer = None
        if system == "B3":
            reviewer = provider.structured(
                "benchmark_review", {"draft": draft, "evidence": case["evidence"]}, Review
            ).model_dump()
            if reviewer["issues"]:
                draft = provider.structured(
                    "benchmark_patch", {"draft": draft, "review": reviewer, **context}, Document
                ).model_dump()
        issues = hard_qa(draft["text"], case["evidence"], case.get("character_limit", 10000))
        accepted = case.get("accepted_text")
        distance = (
            1 - SequenceMatcher(None, draft["text"], accepted).ratio() if accepted is not None else None
        )
        results.append(
            {
                "system": system,
                "hard_issues": issues,
                "edit_distance": distance,
                "review": reviewer,
                "draft": draft,
            }
        )
    return {
        "results": results,
        "quality_conclusion": "Requires blinded human labels; hard-rule counts alone do not prove improvement.",
    }
