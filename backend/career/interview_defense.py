"""Deterministic defense notes from exact frozen claims; missing facts stay missing."""

from career.validation import GOOD

OWNERSHIP_FIELDS = ("problem_definition", "hypothesis", "experiment_design", "implementation", "integration", "result_scope")
OWNERSHIP_LABELS = {"USER": "사용자 직접 수행", "USER_AI_ASSISTED": "사용자 수행 · AI 구현 보조",
                    "USER_MODIFIED_EXISTING_CODE": "기존 코드 수정", "TEAM": "팀 수행", "LAB": "연구실 수행", "UNKNOWN": "확인 필요"}
METRIC_FIELDS = ("dataset", "subset", "experiment_version", "baseline", "denominator", "measurement_context", "measured_at")


def ownership(evidence):
    raw = evidence.get("data", {}).get("ownership", {})
    return {key: raw.get(key, "UNKNOWN") for key in OWNERSHIP_FIELDS}


def boundaries(evidence):
    data = evidence.get("data", {})
    return list(dict.fromkeys(data.get("forbidden_claims", []) + data.get("claim_boundaries", [])))


def metric_notes(evidence):
    result = []
    for metric in evidence.get("data", {}).get("metric_ledger", []):
        if metric.get("status") not in GOOD:
            continue
        result.append({"metric_id": metric.get("id", ""), "name": metric.get("name", ""),
                       "value": metric.get("value"), "unit": metric.get("unit", ""),
                       **{key: metric.get(key) for key in METRIC_FIELDS},
                       "source_id": metric.get("source_id", evidence["source_id"]),
                       "business_effect": metric.get("business_effect", False),
                       "valid_for_claims": metric.get("valid_for_claims", []),
                       "invalid_for_claims": metric.get("invalid_for_claims", []),
                       "missing_information": [key for key in METRIC_FIELDS if metric.get(key) in (None, "", "UNKNOWN")],
                       "status": "FROZEN_MEASUREMENT_RECORD"})
    return result


def speaking_notes(evidence: dict):
    episode = evidence.get("data", {}).get("decision_episode", {})
    role, metrics, limits = ownership(evidence), metric_notes(evidence), boundaries(evidence)
    role_text = "; ".join(f"{key}: {OWNERSHIP_LABELS.get(value, '확인 필요')}" for key, value in role.items())
    fields = {key: episode.get(key, [] if key == "options" else "") for key in
              ("situation", "constraint", "hypothesis", "options", "observation", "unexpected_result", "decision", "reframe", "action", "experiment", "outcome", "lesson")}
    fields["output"] = evidence.get("data", {}).get("output", "")

    def section(label, keys, seconds, fallback=""):
        parts = ["; ".join(fields[key]) if isinstance(fields[key], list) else fields[key] for key in keys if fields[key]]
        return {"label": label, "target_seconds": seconds, "source_quote": "\n".join(parts) or fallback,
                "missing_information": [key for key in keys if not fields[key]], "source_id": evidence["source_id"]}

    plans = {
        "one_minute": [section("만든 산출물·확인한 사실", ["output"], 20, evidence["body"]),
                       {"label": "직접 수행한 범위", "target_seconds": 20, "source_quote": role_text, "source_id": evidence["source_id"],
                        "missing_information": [key for key, value in role.items() if value == "UNKNOWN"]},
                       section("결과와 확인이 필요한 한계", ["outcome"], 20)],
        "three_minute": [section("상황과 제약", ["situation", "constraint"], 40),
                         section("관찰과 선택한 판단", ["observation", "decision"], 55),
                         section("실제 수행·결과", ["action", "outcome"], 55),
                         section("배운 점과 적용 한계", ["lesson"], 30)],
        "five_minute": [section("문제와 초기 가설", ["situation", "constraint", "hypothesis"], 50),
                        section("대안과 관찰·방향 전환", ["options", "observation", "unexpected_result", "reframe"], 75),
                        section("선택한 방법과 실험", ["decision", "experiment", "action"], 75),
                        section("결과의 범위", ["outcome"], 55), section("한계와 이후 판단 기준", ["lesson"], 45)],
    }
    return {duration: {"title": evidence["title"], "evidence_id": evidence["id"], "source_id": evidence["source_id"],
                       "target_seconds": {"one_minute": 60, "three_minute": 180, "five_minute": 300}[duration],
                       "timing_status": "NOT_MEASURED_PRACTICE_REQUIRED", "status": "SOURCE_BOUND_SPEAKING_NOTES",
                       "text": "\n\n".join(s["label"] + ": " + (s["source_quote"] or "확인 필요") for s in sections),
                       "structure": [s["label"] for s in sections], "sections": sections,
                       "ownership": role, "metric_scope": metrics, "forbidden_claims": limits,
                       "missing_information": list(dict.fromkeys([key for s in sections for key in s["missing_information"]]
                                                                  + [key for key, value in role.items() if value == "UNKNOWN"]
                                                                  + (["metric_scope"] if not metrics else [])))}
            for duration, sections in plans.items()}


def build_handoff(bundle: dict, bundle_id: str):
    evidence_by_id = {e["id"]: e for e in bundle.get("evidence", [])}
    artifacts = bundle.get("artifacts", [])
    strategy = next((a["data"] for a in artifacts if a["kind"] == "ApplicationBrief"), {})
    opportunity = next((a["data"] for a in artifacts if a["kind"] == "OpportunityBrief"), {})
    research = next((a["data"] for a in artifacts if a["kind"] == "CompanyResearchResult"), {})
    company_sources = {source["id"]: source for source in research.get("sources", [])}
    claims = []
    for document in artifacts:
        if document["kind"] not in {"Draft", "ResumeContent"}:
            continue
        for claim in document["data"].get("claims", []):
            support = []
            for evidence_id in claim.get("evidence_ids", []):
                evidence = evidence_by_id.get(evidence_id)
                if evidence is None:
                    support.append({"evidence_id": evidence_id, "status": "MISSING_FROM_FROZEN_BUNDLE"})
                    continue
                episode = evidence.get("data", {}).get("decision_episode", {})
                support.append({"evidence_id": evidence_id, "title": evidence["title"], "source_id": evidence["source_id"],
                                "source_quote": evidence["body"], "ownership": ownership(evidence),
                                "why_this_decision": episode.get("decision", ""), "alternatives": episode.get("options", []),
                                "observation": episode.get("observation", ""), "turning_point": episode.get("reframe", ""),
                                "limitations": boundaries(evidence),
                                "metrics": [m for m in metric_notes(evidence) if not claim.get("metric_ids") or m["metric_id"] in claim["metric_ids"]],
                                "missing_information": [key for key in ("decision", "options", "observation") if not episode.get(key)]})
            claims.append({**claim, "document_id": document["id"], "document_version": document["version"],
                           "company_defense_sources": [
                               {"statement": fact["statement"], "source_id": fact["source_id"],
                                "source": company_sources.get(fact["source_id"], {}), "freshness_at_submission": fact["freshness"]}
                               for fact in opportunity.get("company_facts", [])
                               if fact["source_id"] in claim.get("company_source_ids", []) and fact["statement"] == claim["text"]
                           ],
                           "question_id": document.get("slot", ""), "defense_evidence": support,
                           "defense_status": "FROZEN_SOURCE_QUOTATIONS_CONFIRM_MISSING_DETAILS",
                           "followups": ["어떤 관찰과 대안을 근거로 이 판단을 했나요?", "본인이 수행한 범위와 팀·AI 보조 범위는 어디까지인가요?", "수치의 데이터·부분집합·기준선·분모·측정 환경은 무엇인가요?"]})
    result = {
        "submission_bundle_id": bundle_id, "basis": "EXACT_FROZEN_SUBMISSION_ONLY", "claim_defense": claims,
        "ownership_notes": [{"evidence_id": e["id"], "source_id": e["source_id"], "ownership": ownership(e),
                             "missing_information": [key for key, value in ownership(e).items() if value == "UNKNOWN"]} for e in evidence_by_id.values()],
        "metric_scope_notes": [{"evidence_id": e["id"], "source_id": e["source_id"], "raw_source_quote": e["body"],
                                "metrics": metric_notes(e), "boundaries": boundaries(e),
                                "missing_information": [] if metric_notes(e) else ["structured_metric_record", *METRIC_FIELDS]} for e in evidence_by_id.values()],
        "expected_followups": ["왜 이 문제를 해결해야 한다고 판단했나요?", "어떤 관찰이 초기 가설이나 방향을 바꿨나요?",
                               "왜 이 방법을 골랐고 다른 대안은 무엇이었나요?", "직접 수행한 범위와 AI·팀 기여는 어디까지인가요?",
                               "실제 사용자·배포·측정한 업무 성과는 어디까지인가요?", "AI·데이터 업무가 아니어도 이 회사의 본업을 하고 싶은가요?",
                               "현장·기초업무에서 먼저 배워야 할 것은 무엇인가요?"],
        "job_context": {"company": bundle.get("company", ""), "role": bundle.get("role", ""),
                        "base_profession": opportunity.get("base_profession", ""), "actual_outputs": opportunity.get("actual_outputs", [])},
        "fatal_gap_answers": [{"gap": gap, "acknowledgement": "제출 당시 확인되지 않은 수행 범위입니다: " + gap,
                               "frozen_strategy_quote": strategy.get("fatal_gap_strategy", ""),
                               "safe_answer": "이 범위를 직접 수행했다고 주장하지 않겠습니다. 확인된 경험과 보완 계획을 구분해 답해야 합니다.",
                               "missing_information": ["specific_remediation_evidence", "confirmed_learning_plan"],
                               "status": "GAP_ACKNOWLEDGEMENT_NOT_INVENTED_REMEDIATION"} for gap in strategy.get("fatal_gaps", [])],
        "project_explanations": {key: [] for key in ("one_minute", "three_minute", "five_minute")},
    }
    for evidence in evidence_by_id.values():
        speaking = speaking_notes(evidence)
        for duration in result["project_explanations"]:
            result["project_explanations"][duration].append(speaking[duration])
    return result
