"""Display/provider projection only: archived examples have no publication grant.

Stored artifacts and their original hashes remain immutable. Rebuilding a current
WritingPlan uses the projected guide, so screen and writer share the same snapshot.
"""

from copy import deepcopy
from typing import Any


def publishable_guide(guide: dict) -> dict:
    result = deepcopy(guide)
    if result.get("origin") != "ARCHIVED_REFERENCE":
        return result
    result["rights_status"] = "RIGHTS_PENDING"
    result["public_example_mode"] = "NONE"
    result["reference_example"] = {
        "origin": "WITHHELD_RIGHTS_PENDING", "use_as_applicant_fact": False, "paragraphs": [],
        "notice": "예시 전문은 공개 권리를 확인 중입니다. 문항 의도·권장 배분과 출처를 참고해 주세요.",
    }
    source = result.get("source")
    if isinstance(source, dict):
        result["source"] = {key: source[key] for key in
                            ("source_url", "source_paragraph_id", "source_paragraph_sha256") if key in source}
    return result


def publication_projection(value: Any) -> Any:
    """Cover historical nested guide snapshots in views/exports without mutating truth."""
    if isinstance(value, dict):
        if value.get("origin") == "ARCHIVED_REFERENCE" and "guide_id" in value and "reference_example" in value:
            value = publishable_guide(value)
        return {key: publication_projection(item) for key, item in value.items()}
    if isinstance(value, list):
        return [publication_projection(item) for item in value]
    return value
