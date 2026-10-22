"""Offline guide-only retrieval. Rankings are candidates, never evidence or approval."""

import math
import re
from collections import Counter
from collections.abc import Callable

from career.question_contracts import QuestionContract, fingerprint, normalized
from career.question_guide_import import GuideRecord, GuideRelease, catalog
from career.writing_plans import TEMPLATES, family

SEARCH_VERSION = "guide-search-bm25-v1"
# Adapter receives guide text only: no user IDs, personal facts, examples or source instructions.
VectorSearch = Callable[[str, dict[str, str]], dict[str, float]]


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
                and review.content_hash == record.content_hash
                and (not review.permitted_companies or normalized(question.company) in {
                    normalized(value) for value in review.permitted_companies})):
            return review
    return None


def _template(question: QuestionContract) -> dict:
    kind = family(question.raw_text)
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
             releases: tuple[GuideRelease, ...] = (), vector_search: VectorSearch | None = None,
             max_candidates: int = 3) -> dict:
    if type(max_candidates) is not int or not 1 <= max_candidates <= 3:
        raise ValueError("max_candidates must be between 1 and 3")
    rows = catalog(list(records))
    query = " ".join((question.raw_text, *question.required_demands))
    # Unreviewed guides never reach the vector adapter, even if it is configured later.
    released = {row.guide.guide_id: row for row in rows if _release(row, releases, question)}
    documents = {key: " ".join((row.guide.question, *row.guide.required_demands,
                                row.guide.question_intent)) for key, row in released.items()}
    lexical = lexical_scores(query, documents)
    vector: dict[str, float] = {}
    vector_state = "NOT_CONFIGURED"
    if vector_search and documents:
        try:
            scores = vector_search(query, documents)
            if not isinstance(scores, dict) or any(
                key not in documents or isinstance(score, bool) or not isinstance(score, (float, int))
                or not math.isfinite(score) or not -1 <= score <= 1 for key, score in scores.items()
            ):
                raise ValueError("invalid guide vector scores")
            vector = scores
            vector_state = "AVAILABLE"
        except Exception:
            # Provider error messages may contain credentials; return only a fixed status.
            vector_state = "UNAVAILABLE_LEXICAL_ONLY"
    elif vector_search:
        vector_state = "NOT_NEEDED_NO_RELEASED_GUIDES"

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
        exact = same_text and same_scope and known_policy and question.length == guide.length
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
        matches.append({"guide_id": key, "guide_version": guide.version, "guide_snapshot_hash": record.content_hash,
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
              "corpus_revision": fingerprint([(row.guide.guide_id, row.guide.version, row.content_hash) for row in rows]),
              "review_revision": fingerprint(sorted((review.model_dump(mode="json") for review in releases),
                                                     key=lambda row: (row["guide_id"], row["version"], row["review_id"]))),
              "mode": "OFFLINE_PREVIEW", "namespace": "QUESTION_GUIDES_ONLY", "can_execute": False,
              "vector_status": vector_state, "candidates": selected, "rejected": rejected,
              "omitted_candidate_count": len(matches) - len(selected),
              "outcome": selected[0]["match_type"] if selected else "GUIDE_FALLBACK",
              "fallback": _template(question), "count_policy_confirmation_required": question.length.needs_confirmation}
    result["retrieval_run_id"] = fingerprint(result)
    return result
