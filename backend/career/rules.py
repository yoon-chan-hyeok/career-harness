"""Confirmed writing guidance with explicit scope and source validity."""

from sqlalchemy import select

from career.entities import WritingRuleRecord
from career.models import Source
from career.truth import owned
from career.validation import GOOD


def writing_rules(db, user, workspace, question_type="", project_names=()):
    scopes = {
        "GLOBAL": {"*", ""},
        "USER": {user},
        "COMPANY": {workspace.company},
        "ROLE_TYPE": {workspace.role},
        "QUESTION_TYPE": {question_type},
        "PROJECT": set(project_names),
        "INDUSTRY": {workspace.data.get("industry", "")},
    }
    result = []
    for rule in db.scalars(
        select(WritingRuleRecord).where(
            WritingRuleRecord.user_id == user, WritingRuleRecord.status.in_(["CANONICAL", "VERIFIED"])
        )
    ):
        data = rule.data
        domain = "RESUME" if question_type == "RESUME" else "COVER"
        if data.get("domain", "COMMON") not in {"COMMON", domain}:
            continue
        if owned(db, Source, user, rule.source_id).status not in GOOD:
            continue
        from career.promotion import usable_rule

        if not usable_rule(db, user, data):
            continue
        if data["scope_type"] != "GLOBAL" and (
            not data["scope_value"] or data["scope_value"] not in scopes[data["scope_type"]]
        ):
            continue
        result.append({k: data[k] for k in ["rule", "rule_type", "scope_type", "scope_value", "source_id"]})
    return result
