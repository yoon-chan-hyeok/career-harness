"""Explicit human answers for synthetic workflows; never auto-approve in product code."""
from career.final_decision import confirm, inputs


def final_payload(service, workspace):
    current = inputs(service, workspace)
    evidence = current["evidence"][0]
    return {"context_hash": current["context_hash"], "role_noun": current["base_profession"],
        "role_alignment": "MATCH", "assignment_answer": "현재 근거로 실험을 설계하고 결과 보고서를 작성할 수 있습니다.",
        "motivation_answer": "저는 이 직무의 평가 실험과 결과 해석 업무를 배우고 수행하고 싶습니다.",
        "wants_core_work": True, "evidence_answer": "직접 수행한 실험과 검증 기록이 평가 업무와 연결되는 근거입니다.",
        "citations": [{"evidence_id": evidence["id"], "quote": evidence["body"][:2000]}],
        "gaps_answer": "실제 대규모 운영 경험까지 증명하는 것은 아닙니다.", "decision": "PASS",
        "return_stage": "NONE", "confirmed": True}


def confirm_final(service, workspace):
    return confirm(service, workspace, final_payload(service, workspace))
