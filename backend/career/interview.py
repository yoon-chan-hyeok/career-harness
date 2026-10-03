"""Different-duration speaking notes derived exclusively from frozen evidence."""

import re


def explanations(evidence: dict):
    body = evidence["body"]
    episode = evidence.get("data", {}).get("decision_episode", {})
    facts = [part.strip() for part in re.split(r"(?<=[.!?。])\s+|\n+", body) if part.strip()]
    short = " ".join(facts[:2])
    sections = [
        ("상황과 제약", "situation"),
        ("판단", "decision"),
        ("수행", "action"),
        ("결과", "outcome"),
        ("배운 점", "lesson"),
    ]
    detail = "\n\n".join(label + ": " + episode[key] for label, key in sections if episode.get(key))
    limits = evidence.get("data", {}).get("forbidden_claims", [])
    extended = detail or body
    if limits:
        extended += "\n\n주장하지 않을 범위: " + "; ".join(limits)
    return {
        "one_minute": {
            "title": evidence["title"],
            "evidence_id": evidence["id"],
            "text": short,
            "structure": ["산출물", "직접 수행", "결과"],
            "status": "SOURCE_BOUND_SPEAKING_NOTES",
        },
        "three_minute": {
            "title": evidence["title"],
            "evidence_id": evidence["id"],
            "text": detail or body,
            "structure": ["상황·제약", "선택한 방법", "수행·결과"],
            "status": "SOURCE_BOUND_SPEAKING_NOTES",
        },
        "five_minute": {
            "title": evidence["title"],
            "evidence_id": evidence["id"],
            "text": extended,
            "structure": [
                "상황·제약",
                "대안과 선택 기준",
                "실험과 수행 범위",
                "결과의 범위",
                "한계와 배운 점",
            ],
            "missing_information": [label for label, key in sections if not episode.get(key)],
            "status": "SOURCE_BOUND_SPEAKING_NOTES",
        },
    }
