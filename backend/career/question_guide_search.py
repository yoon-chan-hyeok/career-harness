"""Offline guide-only retrieval. Rankings are candidates, never evidence or approval."""

import math
import re
from collections import Counter
from typing import Annotated, Literal

from pydantic import Field

from career.question_contracts import Contract, QuestionContract, fingerprint, normalized
from career.question_guide_import import (
    GuideRecord,
    GuideRelease,
    ReleaseLedger,
    SourceManifest,
    catalog,
    source_manifest,
)
from career.writing_plans import TEMPLATES, family

SEARCH_VERSION = "guide-search-i01-v2"


class OfflineVectorScores(Contract):
    """Precomputed guide-only scores; I01 cannot execute callbacks or provider I/O."""
    namespace: Literal["QUESTION_GUIDES"] = "QUESTION_GUIDES"
    question_revision: str
    corpus_revision: str
    scores: dict[str, Annotated[float, Field(strict=True, ge=-1, le=1, allow_inf_nan=False)]]


class GuideCandidate(Contract):
    request_key: str
    question_contract_ref: dict[str, str | int]
    guide_ref: dict[str, str | int]
    match_type: Literal["EXACT", "ADVISORY_ANALOGY"]
    match_policy: Literal["LEGACY_EXACT", "STRICT_EXACT", "STRUCTURAL_ADVISORY"]
    retrieval_mode: Literal["EXACT_ONLY", "LEXICAL_ONLY", "OFFLINE_HYBRID"]
    status: Literal["CANDIDATE_NOT_APPROVED"] = "CANDIDATE_NOT_APPROVED"
    ranking_explanation: str
    source_manifest: SourceManifest


def _negative_requirement(question: QuestionContract) -> bool:
    # I01 has no semantic model: ambiguous explicit negation must not become positive advice.
    return bool(re.search(r"제외|말고|아닌|아니라|없이|하지\s*마|금지|쓰지|사용하지|배제|\b(?:not|without|exclude)\b",
                          question.raw_text, re.IGNORECASE))


def _exact_policy(question: QuestionContract, record: GuideRecord) -> str | None:
    guide = record.guide
    if (normalized(question.company) != normalized(guide.source_scope.company)
            or normalized(question.role) != normalized(guide.source_scope.role)
            or normalized(question.raw_text) != normalized(guide.question)
            or question.length.maximum != guide.length.maximum
            or question.length.minimum != guide.length.minimum or question.length.unit != guide.length.unit):
        return None
    for field in ("spaces", "newlines", "title"):
        actual, archived = getattr(question.length, field), getattr(guide.length, field)
        if actual != "UNKNOWN" and archived != "UNKNOWN" and actual != archived:
            return None
    if not question.length.needs_confirmation and not guide.length.needs_confirmation and question.length == guide.length:
        return "STRICT_EXACT"
    if record.provenance.get("version") == "ADAPTER_ASSIGNED:legacy-bundled-v1":
        return "LEGACY_EXACT"
    return None


def terms(text: str) -> list[str]:
    """Word + Korean character bigrams. No external tokenizer/model/download is required."""
    words = re.findall(r"[a-z0-9]+|[가-힣]+", text.casefold())
    return [term for word in words for term in ([word] + (
        [word[i:i + 2] for i in range(len(word) - 1)] if re.search(r"[가-힣]", word) else []))]


def lexical_scores(query: str, documents: dict[str, str]) -> dict[str, float]:
    if not documents:
        return {}
    bags = {key: Counter(terms(text)) for key, text in documents.items()}
    avg = sum(sum(bag.values()) for bag in bags.values()) / len(bags) or 1
    result = dict.fromkeys(documents, 0.0)
    for term in set(terms(query)):
        df = sum(term in bag for bag in bags.values())
        idf = math.log(1 + (len(bags) - df + 0.5) / (df + 0.5))
        for key, bag in bags.items():
            tf = bag[term]
            result[key] += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * sum(bag.values()) / avg))
    return result


def _facets(text: str) -> set[str]:
    patterns = {"FAILURE": r"실패", "CONFLICT": r"갈등", "COLLABORATION": r"협업|협력|팀워크",
                "WEAKNESS": r"단점|약점", "MOTIVATION": r"지원.?동기", "VALUES": r"가치관|신념"}
    return {key for key, pattern in patterns.items() if re.search(pattern, text)}


def _release(record: GuideRecord, reviews: tuple[GuideRelease, ...], question: QuestionContract):
    for review in reviews:
        if (review.guide_id == record.guide.guide_id and review.version == record.guide.version
                and review.content_hash == record.content_hash and review.source_rights != "RESTRICTED"
                and (not review.permitted_companies or normalized(question.company) in {
                    normalized(value) for value in review.permitted_companies})):
            return review
    return None


def _template(question: QuestionContract) -> dict:
    kind = "OTHER" if _negative_requirement(question) else family(question.raw_text)
    title, intent, labels, instructions, weights = TEMPLATES[kind]
    # These are proposed content budgets, never an official form counter or fixed paragraph count.
    counts = [question.length.maximum * weight // 100 for weight in weights]
    counts[-1] += question.length.maximum - sum(counts)
    return {"origin": "FALLBACK_TEMPLATE", "family": kind, "title": title, "intent": intent,
            "source_ref": None, "actual_limit": question.length.model_dump(mode="json"),
            "budget_status": "NEEDS_COUNT_POLICY_CONFIRMATION" if question.length.needs_confirmation
            else "PROPOSED_NOT_OFFICIAL", "fixed_paragraph_count": False,
            "allocation": [{"content": label, "suggested_budget": count, "unit": question.length.unit,
                            "hint": hint} for label, count, hint in zip(labels, counts, instructions, strict=True)]}


def retrieve(question: QuestionContract, records: list[GuideRecord] | tuple[GuideRecord, ...], *,
             releases: tuple[GuideRelease, ...] = (), vector_scores: OfflineVectorScores | None = None,
             max_candidates: int = 3, enabled: bool = False) -> dict:
    if type(max_candidates) is not int or not 1 <= max_candidates <= 3:
        raise ValueError("max_candidates must be between 1 and 3")
    if type(enabled) is not bool:
        raise ValueError("enabled must be a boolean")
    releases = ReleaseLedger(reviews=releases).reviews if enabled else ()
    rows = catalog(list(records)) if enabled else ()
    corpus_revision = fingerprint([(row.guide.guide_id, row.guide.version, row.content_hash) for row in rows])
    review_revision = fingerprint(sorted((review.model_dump(mode="json") for review in releases),
                                        key=lambda row: (row["guide_id"], row["version"], row["review_id"])))
    query = " ".join((question.raw_text, *question.required_demands))
    # Corpus and query are version-bound; no arbitrary callback can run during a preview.
    released = {row.guide.guide_id: row for row in rows if _release(row, releases, question)}
    exact_ids = {key for key, row in released.items() if _exact_policy(question, row)
                 and not _negative_requirement(question)
                 and all(any(normalized(demand) in normalized(value) for value in
                             (*row.guide.required_demands, row.guide.question)) for demand in question.required_demands)
                 and not any(normalized(topic) in normalized(" ".join((row.guide.question,
                     *row.guide.required_demands, row.guide.question_intent,
                     *(part.content for part in row.guide.allocation)))) for topic in question.excluded_topics)}
    documents = {key: " ".join((row.guide.question, *row.guide.required_demands,
                                row.guide.question_intent)) for key, row in released.items()}
    lexical = {} if exact_ids or not enabled else lexical_scores(query, documents)
    vector: dict[str, float] = {}
    vector_state = "NOT_NEEDED_EXACT" if exact_ids else "NOT_CONFIGURED"
    if not exact_ids and vector_scores is not None and documents:
        try:
            if not isinstance(vector_scores, OfflineVectorScores):
                raise ValueError("offline score data required")
            validated_index = OfflineVectorScores.model_validate(vector_scores.model_dump())
            if (validated_index.question_revision != question.revision or validated_index.corpus_revision != corpus_revision
                    or any(key not in documents for key in validated_index.scores)):
                raise ValueError("invalid guide vector scores")
            vector = validated_index.scores
            vector_state = "PRECOMPUTED_AVAILABLE"
        except (ValueError, TypeError):
            vector_state = "UNAVAILABLE_LEXICAL_ONLY"
    elif not exact_ids and vector_scores is not None:
        vector_state = "NOT_NEEDED_NO_RELEASED_GUIDES"
    retrieval_mode = "EXACT_ONLY" if exact_ids else "OFFLINE_HYBRID" if vector else "LEXICAL_ONLY"
    request_key = fingerprint([question.revision, corpus_revision, review_revision, SEARCH_VERSION,
                               enabled, max_candidates, vector_state, vector])

    # Reciprocal rank fusion orders candidates only. It is not a calibrated success threshold.
    fused = dict.fromkeys(documents, 0.0)
    for scores in (lexical, vector):
        for rank, key in enumerate(sorted((key for key in scores if scores[key] > 0),
                                          key=lambda key: (-scores[key], key)), start=1):
            fused[key] += 1 / (60 + rank)
    matches, rejected = [], []
    for record in rows:
        guide, key = record.guide, record.guide.guide_id
        review = _release(record, releases, question)
        reasons = []
        same_text = normalized(question.raw_text) == normalized(guide.question)
        same_scope = (normalized(question.company) == normalized(guide.source_scope.company)
                      and normalized(question.role) == normalized(guide.source_scope.role))
        guide_demands = [normalized(value) for value in (*guide.required_demands, guide.question)]
        covered = [demand for demand in question.required_demands
                   if any(normalized(demand) in value for value in guide_demands)]
        missing = [demand for demand in question.required_demands if demand not in covered]
        contradictions = [topic for topic in question.excluded_topics if normalized(topic) in normalized(
            " ".join((guide.question, *guide.required_demands, guide.question_intent,
                      *(part.content for part in guide.allocation))))]
        if review is None:
            reasons.append("RIGHTS_OR_SEMANTIC_REVIEW_REQUIRED")
        if _negative_requirement(question):
            reasons.append("NEGATIVE_REQUIREMENT_REQUIRES_REVIEW")
        if exact_ids and key not in exact_ids:
            reasons.append("EXACT_MATCH_AVAILABLE")
        if not same_text and (family(question.raw_text) == "OTHER" or family(question.raw_text) != record.derived_family):
            reasons.append("QUESTION_FAMILY_MISMATCH_OR_UNKNOWN")
        if _facets(question.raw_text) - _facets(guide.question):
            reasons.append("REQUIRED_QUESTION_FACET_MISSING")
        if missing:
            reasons.append("EXPLICIT_REQUIRED_DEMAND_MISSING")
        if contradictions:
            reasons.append("EXCLUDED_TOPIC_CONFLICT")
        if question.length.unit != guide.length.unit:
            reasons.append("LENGTH_UNIT_MISMATCH")
        # A known counter conflict cannot be repaired by a guide's suggested budget.
        policy_conflict = any(left != "UNKNOWN" and right != "UNKNOWN" and left != right
                              for left, right in zip(
                                  (question.length.spaces, question.length.newlines, question.length.title,
                                   question.length.encoding if question.length.unit == "BYTES" else "UNKNOWN"),
                                  (guide.length.spaces, guide.length.newlines, guide.length.title,
                                   guide.length.encoding if guide.length.unit == "BYTES" else "UNKNOWN"), strict=True))
        if policy_conflict:
            reasons.append("COUNT_POLICY_CONFLICT")
        if not same_text and lexical.get(key, 0) <= 0 and vector.get(key, 0) <= 0:
            reasons.append("NO_RETRIEVAL_SIGNAL")
        if reasons:
            rejected.append({"guide_id": key, "version": guide.version, "match_type": "REJECTED",
                             "reasons": reasons, "missing_demands": missing,
                             "contradictory_demands": contradictions})
            continue
        known_policy = not question.length.needs_confirmation and not guide.length.needs_confirmation
        match_policy = _exact_policy(question, record)
        exact = match_policy is not None
        original_counts = [part.approximate_characters for part in guide.allocation]
        counts = original_counts if exact else [question.length.maximum * count // sum(original_counts)
                                               for count in original_counts]
        counts[-1] += (sum(original_counts) if exact else question.length.maximum) - sum(counts)
        warnings = ["구조 참고 자료이며 예시의 기관·프로젝트·수치는 지원자 사실이 아닙니다.",
                    "개인 근거·소재·Claim 승인과 문항 간 배분은 별도로 확인해야 합니다."]
        if not exact:
            warnings.append("유사 문항의 내용 기능을 참고한 새 제안입니다. 현재 회사의 공식 구성 안내가 아닙니다.")
        if not known_policy:
            warnings.append("공백·줄바꿈·제목 또는 바이트 계산 기준이 불명확합니다. 실제 지원 폼 확인이 필요합니다.")
        manifest = source_manifest(record, review)
        candidate = GuideCandidate.model_validate({
            "request_key": request_key, "question_contract_ref": {"id": question.question_id, "version": question.version},
            "guide_ref": {"id": key, "version": guide.version}, "match_type": "EXACT" if exact else "ADVISORY_ANALOGY",
            "match_policy": match_policy or "STRUCTURAL_ADVISORY", "retrieval_mode": retrieval_mode,
            "ranking_explanation": "동일 원문의 구조 참고; 계수 정책은 별도로 확인" if exact else
            "문항 유형·명시 요구를 확인한 구조 참고 후보; 의미 적합성은 사람 검토 필요",
            "source_manifest": manifest})
        matches.append({**candidate.model_dump(mode="json"),
                        "rights_status": manifest.rights_status, "public_example_mode": "NONE",
                        "guide_id": key, "guide_version": guide.version, "guide_snapshot_hash": record.content_hash,
                        "match_type": "EXACT" if exact else "ADVISORY_ANALOGY",
                        "origin": "EXACT_ARCHIVE" if exact else "ANALOGICAL_ADVISORY",
                        "selected_by": "SYSTEM_EXACT" if exact else "NONE", "approved": False,
                        "source_ref": guide.source_ref, "source_scope": guide.source_scope.model_dump(),
                        "source_verified_live": False, "release_review_id": review.review_id if review else None,
                        "source_sha256": record.original_sha256, "provenance": record.provenance,
                        "candidate_scores": {"lexical": lexical.get(key, 0), "vector": vector.get(key),
                                             "rerank": None, "rank_fusion": fused.get(key, 0)},
                        "semantic_assessment": "STRUCTURAL_CHECK_ONLY_NOT_CALIBRATED",
                        "matched_demands": covered, "missing_demands": missing, "contradictory_demands": contradictions,
                        "length_compatible": question.length == guide.length if known_policy else None,
                        "count_policy_confirmation_required": not known_policy,
                        "scope_transfer": not same_scope,
                        "actual_limit": question.length.model_dump(),
                        "source_allocation": [part.model_dump() for part in guide.allocation],
                        "suggested_allocation": [{"content": part.content, "suggested_budget": count,
                                                  "unit": question.length.unit}
                                                 for part, count in zip(guide.allocation, counts, strict=True)],
                        "intent": guide.question_intent, "fixed_paragraph_count": False,
                        "reference_example_mode": "NONE", "reference_examples_are_applicant_facts": False,
                        "warnings": warnings})
    matches.sort(key=lambda row: (row["match_type"] != "EXACT", -row["candidate_scores"]["rank_fusion"], row["guide_id"]))
    selected = matches[:max_candidates]
    result = {"version": SEARCH_VERSION, "question_contract_revision": question.revision,
              "corpus_revision": corpus_revision, "request_key": request_key,
              "retrieval_mode": retrieval_mode, "semantic_search_executed": False,
              "feature_enabled": enabled, "fallback_reason": "FEATURE_DISABLED" if not enabled else
              "NEGATIVE_REQUIREMENT_REQUIRES_REVIEW" if _negative_requirement(question) else None,
              "review_revision": review_revision,
              "mode": "OFFLINE_PREVIEW", "namespace": "QUESTION_GUIDES_ONLY", "can_execute": False,
              "vector_status": vector_state, "candidates": selected, "rejected": rejected,
              "omitted_candidate_count": len(matches) - len(selected),
              "outcome": selected[0]["match_type"] if selected else "GUIDE_FALLBACK",
              "fallback": _template(question), "count_policy_confirmation_required": question.length.needs_confirmation
              or any(item["count_policy_confirmation_required"] for item in selected)}
    result["retrieval_run_id"] = fingerprint(result)
    return result
