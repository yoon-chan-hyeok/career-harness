# ruff: noqa: F811 -- reusable workflow fixture
from threading import Barrier, get_ident

from career.parallel_qa import run
from career.schemas import Review
from test_workflow import flow  # noqa: F401


def test_independent_reviewers_execute_on_distinct_workers_without_db_session_access(flow):
    service, _, _ = flow
    barrier = Barrier(2)
    workers = set()
    owner_thread = get_ident()

    class Provider:
        last_trace = {"model": "parallel-fixture"}

        def structured(self, stage, context, schema):
            assert get_ident() != owner_thread
            workers.add(get_ident())
            barrier.wait(timeout=3)
            return schema.model_validate({"issues": [], "followups": [stage]})

    service.provider = Provider()
    result = run(
        service,
        [("fact_reviewer", {"evidence": []}, Review), ("recruiter", {"jd": "JD", "draft": "Draft"}, Review)],
    )
    assert len(workers) == 2
    assert all(value is not None for value in result)
    assert [value["followups"][0] for value in result if value is not None] == ["fact_reviewer", "recruiter"]
