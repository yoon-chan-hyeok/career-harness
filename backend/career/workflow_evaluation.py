"""Ablations that execute the product Workflow in rolled-back evaluation workspaces."""

from difflib import SequenceMatcher

from sqlalchemy import select

from career.models import Artifact, PromptRun
from career.runtime_trace import emit_trace, input_hash, trace_context, trace_sink
from career.schemas import Document
from career.truth import view
from career.validation import hard_qa
from career.workflow import Workflow


def workflow_ablation(service, workspace, question_id, systems=("B0", "B1", "B2", "B3"), accepted_text=None):
    from career.human_review import resolve
    from career.retrieval import configured_embedder, search

    original = service.ws(workspace)
    question = dict(service.question(workspace, question_id))
    source = {
        "workspace_id": original.id,
        "jd": original.jd_raw,
        "company": original.company,
        "role": original.role,
    }
    if not systems or not set(systems) <= {"B0", "B1", "B2", "B3"} or len(set(systems)) != len(systems):
        raise ValueError("중복 없는 B0~B3 평가 구성을 선택해 주세요.")
    from career.providers import OpenAIProvider

    provider = service.provider or OpenAIProvider()
    traces, results = [], []
    sink_token = trace_sink.set(
        lambda stage, name, data: traces.append({"stage": stage, "provider": name, "data": data})
    )
    try:
        for system in systems:
            token = trace_context.set(
                {
                    "workspace_id": workspace,
                    "question_id": question_id,
                    "prompt_version": "workflow-ablation-v1",
                }
            )
            transaction = service.db.begin_nested()
            try:
                flow = Workflow(service.db, service.user, provider)
                clone = flow.create(source["company"], source["role"], source["jd"], "GUIDED")
                if system in {"B0", "B1"}:
                    candidates = search(
                        service.db,
                        service.user,
                        "" if system == "B0" else source["jd"] + " " + question["text"],
                        embedder=None if system == "B0" else configured_embedder(service.db),
                        limit=100 if system == "B0" else 12,
                    )
                    context = {
                        "jd": source["jd"],
                        "question": question["text"],
                        "character_limit": question["limit"],
                        "task": "Write under confirmed facts and ownership only. This isolated ablation has no strategy or approved claim stage.",
                        "broad_context" if system == "B0" else "retrieved_evidence": candidates,
                    }
                    output = flow.ai("benchmark_writer", context, Document)
                    evidence = candidates
                    review = None
                    revision_count = 0
                else:
                    flow.analyze(clone.id)
                    pack = flow.map_evidence(clone.id)
                    flow.strategy(clone.id)
                    # Evaluation-only simulated approval is never a real user acceptance event.
                    flow.approve_strategy(clone.id)
                    q = flow.add_question(clone.id, question["text"], question["limit"])
                    flow.question_brief(clone.id, q["id"])
                    flow.approve_question(clone.id, q["id"])
                    document = flow.draft(clone.id, q["id"])
                    evidence = flow.selected(document.data["selected_evidence_ids"])
                    review = None
                    revision_count = 0
                    if system == "B3":
                        for attempt in range(3):
                            review = flow.review(clone.id, q["id"])
                            if not review.data["issues"] or attempt == 2:
                                break
                            proposal = flow.revise(clone.id, q["id"])
                            resolve(flow, clone.id, proposal["id"], "ACCEPT")
                            revision_count += 1
                        document = flow.artifact(clone.id, "Draft", q["id"])
                    output = dict(document.data)
                    artifacts = [
                        view(a)
                        for a in service.db.scalars(
                            select(Artifact).where(
                                Artifact.workspace_id == clone.id, Artifact.user_id == service.user
                            )
                        )
                    ]
                    assert pack.kind == "EvidencePack"
                results.append(
                    {
                        "system": system,
                        "status": "COMPLETED",
                        "draft": output,
                        "review": review.data if isinstance(review, Artifact) else review,
                        "hard_issues": hard_qa(output["text"], evidence, question["limit"]),
                        "edit_distance": 1 - SequenceMatcher(None, output["text"], accepted_text).ratio()
                        if accepted_text is not None
                        else None,
                        "revision_count": revision_count,
                        "evaluation_artifact_snapshots": artifacts if system in {"B2", "B3"} else [],
                        "approval_basis": "SIMULATED_FOR_ISOLATED_EVAL_NOT_USER_ACCEPTANCE"
                        if system in {"B2", "B3"}
                        else "NO_STRATEGY_STAGE",
                    }
                )
            except Exception as error:
                results.append(
                    {
                        "system": system,
                        "status": "FAILED",
                        "error_code": type(error).__name__,
                        "input_hash": input_hash(source),
                        "quality_conclusion": "NO_COMPLETED_OUTPUT",
                    }
                )
            finally:
                transaction.rollback()
                trace_context.reset(token)
    finally:
        trace_sink.reset(sink_token)
    for trace in traces:
        trace["data"] = {
            **trace["data"],
            "evaluation_workspace_id": trace["data"].get("workspace_id"),
            "workspace_id": workspace,
        }
        service.db.add(PromptRun(user_id=service.user, **trace))
        emit_trace(trace["stage"], trace["provider"], trace["data"])
    return {
        "runner": "ACTUAL_PRODUCT_WORKFLOW_ABLATION",
        "input_hash": input_hash(source),
        "source_workspace_id": workspace,
        "source_question_id": question_id,
        "results": results,
        "isolation": "EVALUATION_WORKSPACES_ROLLED_BACK_ORIGINAL_UNCHANGED",
        "quality_conclusion": "REQUIRES_BLINDED_HUMAN_LABELS_NO_CAUSAL_IMPROVEMENT_CLAIM",
    }
