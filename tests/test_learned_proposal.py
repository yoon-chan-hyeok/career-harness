from career.promotion import correction_cases, propose_from_corrections
from sqlalchemy import select
from test_promotion_postmortem import candidate


def test_repeat_corrections_propose_candidate_only_and_deduplicate_before_new_model_call(db):
    from career.entities import WritingRuleRecord

    seed = candidate(db)
    ids = seed.data["source_case_ids"]
    calls = []

    class Provider:
        def structured(self, stage, context, schema):
            calls.append(stage)
            return schema.model_validate(
                {"rule": "판단을 앞에 쓴다", "reason": "두 실제 교정에서 같은 선호", "source_case_ids": ids}
            )

    proposed = propose_from_corrections(db, "a", ids, Provider())
    assert proposed["status"] == "CANDIDATE" and proposed["data"]["scope_type"] == "USER"
    assert propose_from_corrections(db, "a", ids, Provider())["id"] == proposed["id"]
    assert calls == ["rule_candidate"]
    assert all(row.status == "CANDIDATE" for row in db.scalars(select(WritingRuleRecord)))
    assert len(correction_cases(db, "a")) == 2
    assert correction_cases(db, "b") == []
