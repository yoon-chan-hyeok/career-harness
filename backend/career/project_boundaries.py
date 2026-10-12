"""Explicit project guidance bindings, kept separate from candidate facts."""

import hashlib
import json
import re

from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import select
from sqlalchemy.orm import Session

from career.artifacts import stale
from career.db import Record
from career.models import Evidence, Source
from career.references import references
from career.rulebook import sections
from career.truth import owned
from career.validation import GOOD


class Binding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rule_id: str = Field(max_length=200)
    evidence_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: StrictBool


# Activate a bounded check only when its prohibition occurs in the chosen rule.
# Other source text remains guidance for review, never a new candidate fact.
CHECKS = {
    "FULL_BUILD": (
        r"전체 시스템을 처음부터 개발했다고 쓰지 않는다",
        "전체 시스템 직접 개발 주장",
        r"(?:(?:전체|모든)\s*시스템|시스템\s*전체).{0,20}?(?:처음부터|직접|독자적|단독).{0,18}?(?:개발|구현|구축)",
    ),
    "AGENT_BUILD": (
        r"Agent 구축 경험으로 과장하지 않는다",
        "에이전트 구축 경험으로 확대",
        r"(?:에이전트|agents?)(?:\s*시스템|\s*워크플로)?(?:를|을)?\s*(?:(?:직접|처음부터|독자적으로|단독으로)\s*)?(?:구축|개발|구현|만들)",
    ),
    "DEPLOYMENT": (
        r"실제 서비스 배포 성과로 표현하지 않는다",
        "실제 서비스 배포 성과 주장",
        r"(?:실제\s*서비스|실서비스|상용\s*서비스|프로덕션|production)(?:에|를|을)?\s*.{0,12}?(?:배포|운영|도입|적용)",
    ),
    "FORMAL_RATE": (
        r"정식 FAR/FRR 개선",
        "정식 FAR/FRR 개선 주장",
        r"(?:FAR|FRR|오수락률|오거부율).{0,15}?(?:개선|낮췄|줄였|감소시켰)",
    ),
    "MEASURED_SAVING": (
        r"실제 운영에서 검수시간/비용 감소를 측정한 것은 아니",
        "측정한 운영 시간·비용 절감 주장",
        r"(?:검수\s*시간|검토\s*시간|비용|review time|cost).{0,15}?(?:줄였|절감|감소시켰|단축)",
    ),
}
# Inspect the assertion's own clause. An unrelated later negation must not hide it.
_NON_ASSERTION = re.compile(
    r"^(?:(?:하|되)지\s*(?:않|못)|(?:한|된|했다고|하였다고)\s*"
    r"(?:(?:것|적|경험|성과)(?:은|는|이|가)?\s*)?(?:아니|아닙|아님|없)|"
    r"(?:하|되)(?:고\s*싶|려)|(?:할|될)\s*수|"
    r"(?:할|하는|될|을|를|은|는|의)?\s*(?:계획|예정|목표|가능성|가능하|가능했))"
)
_CLAUSE = re.compile(r"[,;\n]|(?:했지만|하였지만|했으나|하였으나|하지만|그러나)")


def fingerprint(evidence: Evidence) -> str:
    value = {
        "id": evidence.id,
        "source_id": evidence.source_id,
        "status": evidence.status,
        "title": evidence.title,
        "body": evidence.body,
        "data": evidence.data,
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def catalog(db: Session, user: str) -> list[dict]:
    result = []
    for ref in references(db, user):
        if ref.data["key"] != "cover" or not ref.data["active"]:
            continue
        if owned(db, Source, user, ref.data["source_id"]).status not in GOOD:
            continue
        for section in sections(ref.data["content"]):
            if section.chapter != "10" or section.excluded or len(section.path) < 2:
                continue
            rule = section.view("project-boundary")
            rule.update(
                {
                    "id": ref.data["content_hash"] + ":" + rule["rule_id"],
                    "title": section.title,
                    "source_id": ref.data["source_id"],
                    "reference_id": ref.id,
                    "content_hash": ref.data["content_hash"],
                    "fact_authority": False,
                    "checks": [
                        {"code": code, "label": label, "source_quote": match.group(0)}
                        for code, (trigger, label, _) in CHECKS.items()
                        if (match := re.search(trigger, section.text, re.I))
                    ],
                }
            )
            result.append(rule)
    return result


def current(db: Session, user: str, evidence_id: str) -> Record | None:
    rows = db.scalars(
        select(Record).where(
            Record.user_id == user,
            Record.kind == "ProjectBoundary",
            Record.data["evidence_id"].as_string() == evidence_id,
        )
    )
    return max(rows, key=lambda r: r.data["version"], default=None)


def suggested(rules: list[dict], evidence: Evidence) -> str:
    def title(value):
        return re.sub(r"[\W_]", "", value).casefold()

    matches = [rule["id"] for rule in rules if title(rule["title"]) == title(evidence.title)]
    return matches[0] if len(matches) == 1 else ""


def projection(db: Session, user: str, evidence: Evidence, *, rules: list[dict] | None = None) -> dict | None:
    record = current(db, user, evidence.id)
    rules = catalog(db, user) if rules is None else rules
    if record is None:
        if suggested(rules, evidence):
            raise ValueError(
                "이 경험과 이름이 같은 프로젝트 규칙이 있습니다. 경험 정리에서 적용 여부를 직접 확인해 주세요."
            )
        return None
    if record.data["evidence_hash"] != fingerprint(evidence):
        raise ValueError(
            "프로젝트 표현 제한을 확인한 경험이 변경됐습니다. 경험 정리에서 연결을 다시 확인해 주세요."
        )
    if not record.data["rule_id"]:
        return None
    rule = next((r for r in rules if r["id"] == record.data["rule_id"]), None)
    if rule is None:
        raise ValueError("프로젝트 표현 제한의 원문이 변경됐습니다. 경험 정리에서 연결을 다시 확인해 주세요.")
    return {
        **rule,
        "binding_id": record.id,
        "binding_version": record.data["version"],
        "evidence_id": evidence.id,
        "authority": "EXPRESSION_CONSTRAINT_ONLY_NOT_CANDIDATE_FACT",
        "instruction": "선택 근거에만 적용한다. 예시·수치·과거 성과를 사실로 사용하지 않는다. 원문의 제한과 강조점을 작성·검수에서 대조한다.",
    }


def context(db: Session, user: str, evidence_id: str) -> dict:
    evidence = owned(db, Evidence, user, evidence_id)
    record = current(db, user, evidence.id)
    rules = catalog(db, user)
    try:
        projection(db, user, evidence, rules=rules)
        needs_review = False
    except ValueError:
        needs_review = True
    return {
        "evidence_hash": fingerprint(evidence),
        "rules": rules,
        "suggested_rule_id": suggested(rules, evidence),
        "binding": record.data if record else None,
        "needs_review": needs_review,
    }


def bind(db: Session, user: str, evidence_id: str, payload: Binding | dict) -> dict:
    data = Binding.model_validate(payload)
    evidence = db.scalar(
        select(Evidence).where(Evidence.user_id == user, Evidence.id == evidence_id).with_for_update()
    )
    if evidence is None:
        raise LookupError("찾을 수 없는 항목입니다.")
    if not data.confirmed or data.evidence_hash != fingerprint(evidence):
        raise ValueError("현재 경험과 프로젝트 규칙의 대응을 직접 확인해 주세요.")
    if evidence.kind == "EXPRESSION" or evidence.status not in GOOD:
        raise ValueError("확인된 사실 근거에만 프로젝트 규칙을 연결할 수 있습니다.")
    if owned(db, Source, user, evidence.source_id).status not in GOOD:
        raise ValueError("근거 출처가 유효하지 않습니다.")
    rule = next((r for r in catalog(db, user) if r["id"] == data.rule_id), None)
    if data.rule_id and rule is None:
        raise ValueError("현재 활성 원문에 있는 프로젝트 규칙을 선택해 주세요.")
    old = current(db, user, evidence.id)
    value = data.model_dump() | {
        "evidence_id": evidence.id,
        "fact_authority": False,
        "source_id": rule["source_id"] if rule else None,
        "title": rule["title"] if rule else None,
    }
    if old and all(old.data.get(k) == v for k, v in value.items()):
        return {"binding": old.data, "stale_artifacts": []}
    record = Record(
        user_id=user, kind="ProjectBoundary", data=value | {"version": old.data["version"] + 1 if old else 1}
    )
    db.add(record)
    db.flush()
    return {"binding": record.data, "stale_artifacts": stale(db, user, [evidence.id])}


def document_issues(document: dict, evidence: list[dict]) -> list[dict]:
    issues = []
    for item in evidence:
        rule = item.get("data", {}).get("project_boundary")
        if not rule:
            continue
        claims = [c["text"] for c in document.get("claims", []) if item["id"] in c.get("evidence_ids", [])]
        for check in rule["checks"]:
            for claim in claims:
                for clause in _CLAUSE.split(claim):
                    for match in re.finditer(CHECKS[check["code"]][2], clause, re.I):
                        tail = clause[match.end() :].strip()
                        if _NON_ASSERTION.match(tail):
                            continue
                        issues.append(
                            {
                                "code": "PROJECT_BOUNDARY_" + check["code"],
                                "priority": "P1",
                                "message": f"{item['title']}: {check['label']} — 문장: {clause.strip()} / 제한 원문: {check['source_quote']}",
                                "evidence_id": item["id"],
                                "source_id": rule["source_id"],
                            }
                        )
    return issues
