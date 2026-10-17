import os
from copy import deepcopy
from hashlib import sha256
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from career.artifacts import fresh, latest, lock, save, stale
from career.db import Record, now, uid
from career.document_qa import skimmability_qa
from career.models import Artifact, Evidence, Fact, PromptRun, Workspace
from career.prompt_cache import identity_scope
from career.provider_config import provider_settings
from career.providers import (
    ManualResearchProvider,
    OpenAIProvider,
    OpenAIWebResearchProvider,
    ProviderUnavailable,
    configured_provider,
)
from career.resume import ResumeContent, legacy_sections, structured_document
from career.retrieval import compile_context, configured_embedder, search
from career.runtime_trace import emit_trace, input_hash, trace_context, trace_sink
from career.schemas import (
    ApplicationBrief,
    Document,
    EvidencePack,
    OpportunityBrief,
    Patch,
    QuestionBrief,
    ResearchResult,
    ResumeBrief,
    Review,
)
from career.telemetry import feedback
from career.truth import canonical, owned, view
from career.validation import GOOD, hard_qa, ledger_coverage


class Workflow:
    def __init__(self, db: Session, user: str, provider=None):
        self.db, self.user, self.provider = db, user, provider
        self.current_workspace: str | None = None
        self.current_model = "manual"
        self.input_artifact_ids: set[str] = set()

    def ws(self, ident: str) -> Workspace:
        row = self.db.scalar(
            select(Workspace).where(Workspace.user_id == self.user, Workspace.id == ident).with_for_update()
        )
        if row is None:
            raise LookupError("지원 작업을 찾을 수 없습니다.")
        if self.current_workspace != row.id:
            self.input_artifact_ids.clear()
        self.current_workspace = row.id
        return row

    def artifact(self, ident: str, kind: str, slot="", current=True) -> Artifact:
        item = latest(self.db, self.user, ident, kind, slot)
        assert item is not None
        if current:
            fresh(self.db, self.user, item)
        self.input_artifact_ids.add(item.id)
        return item

    def editable(self, ws: Workspace):
        if ws.state in {"SUBMISSION_FROZEN", "SUBMITTED", "CLOSED"}:
            raise ValueError("제출 보관본이 있는 작업입니다. 새 작업에서 수정해 주세요.")

    def question_state(self, ident: str, qid: str, state: str):
        ws = self.ws(ident)
        ws.data = {**ws.data, "question_states": {**ws.data.get("question_states", {}), qid: state}}
        from career.projections import sync_workspace

        sync_workspace(self.db, ws)

    def resume_state(self, ident: str, state: str):
        ws = self.ws(ident)
        ws.data = {**ws.data, "resume_state": state}

    def ai(self, stage: str, context: dict, schema):
        from career.references import compile_pack

        reference_pack = compile_pack(self.db, self.user, stage, context.get("document_domain", ""))
        context = {**context, "supplemental_guidance": reference_pack}
        metadata = {
            **trace_context.get(),
            "workspace_id": self.current_workspace,
            "input_artifact_ids": sorted(self.input_artifact_ids),
            "prompt_version": "v2-supplement" if reference_pack["references"] else "v1",
            "input_hash_only": True,
            "reference_pack": reference_pack["pack"],
            "reference_versions": [
                {k: r[k] for k in ("key", "version", "content_hash")} for r in reference_pack["references"]
            ],
        }
        token = trace_context.set(metadata)
        sink_token = None
        if trace_sink.get() is None:
            sink_token = trace_sink.set(
                lambda key, name, data: self.db.add(
                    PromptRun(user_id=self.user, stage=key, provider=name, data=data)
                )
            )
        provider = self.provider
        try:
            provider = self.provider or configured_provider()
            with identity_scope(self.user):
                result = provider.structured(stage, context, schema)
            if not getattr(provider, "trace_emitting", False):
                emit_trace(
                    stage,
                    type(provider).__name__,
                    {
                        **getattr(provider, "last_trace", {}),
                        "input_hash": input_hash(context),
                        "status": "COMPLETED",
                    },
                )
        except Exception:
            if provider is None or not getattr(provider, "trace_emitting", False):
                emit_trace(
                    stage,
                    type(provider).__name__ if provider else "ConfiguredProvider",
                    {
                        "input_hash": input_hash(context),
                        "status": "FAILED",
                        "error_code": "PROVIDER_UNAVAILABLE",
                    },
                )
            raise
        finally:
            trace_context.reset(token)
            if sink_token is not None:
                trace_sink.reset(sink_token)
        self.current_model = str(
            getattr(provider, "last_trace", {}).get("model", os.getenv("OPENAI_MODEL", "unknown"))
        )
        return result.model_dump()

    def reference_sources(self, stage: str, domain=""):
        from career.references import compile_pack

        return [r["source_id"] for r in compile_pack(self.db, self.user, stage, domain)["references"]]

    def bounded_decision(self, task: str, state: dict, options: list[str]):
        from career.decisions import JevDecisionProvider, LLMStructuredDecisionProvider, shadow_decision

        primary = LLMStructuredDecisionProvider(self.provider or configured_provider())
        if os.getenv("JEV_SHADOW_ENABLED") == "1" and os.getenv("JEV_API_KEY"):
            return shadow_decision(self.db, self.user, primary, JevDecisionProvider(), task, state, options)
        return primary.choose(task, state, options)

    def create(self, company: str, role: str, jd: str, mode="GUIDED"):
        if not company.strip() or not role.strip() or not jd.strip():
            raise ValueError("회사, 직무와 공고 내용을 입력해 주세요.")
        if mode not in {"GUIDED", "FAST"}:
            raise ValueError("지원하지 않는 진행 모드입니다.")
        ws = Workspace(
            user_id=self.user, company=company, role=role, jd_raw=jd, mode=mode, data={"questions": []}
        )
        self.db.add(ws)
        self.db.flush()
        from career.projections import sync_workspace

        sync_workspace(self.db, ws)
        return ws

    def research(self, ident: str, live=False, manual=None):
        ws = self.ws(ident)
        self.editable(ws)
        existing = latest(self.db, self.user, ident, "CompanyResearchResult", required=False)
        if manual is None and existing and existing.data.get("source_documents"):
            fresh(self.db, self.user, existing)
            return existing
        status = "MANUAL_JD_ONLY"
        result = ManualResearchProvider().research(ws.company, ws.role, ws.jd_raw)
        if manual:
            result = ResearchResult.model_validate(manual)
            source_ids = {s.id for s in result.sources}
            if any(f.source_id not in source_ids for f in result.official_facts + result.external_evidence):
                raise ValueError("각 회사 사실에 출처를 연결해 주세요.")
            for fact in result.official_facts + result.external_evidence:
                fact.source_type = "USER_SUPPLIED"
            status = "USER_SUPPLIED_RESEARCH"
        if live and not manual:
            try:
                if provider_settings().provider != "openai":
                    raise ValueError("선택한 제공자는 웹 검색 도구를 지원하지 않습니다.")
                result = OpenAIWebResearchProvider(OpenAIProvider()).research(ws.company, ws.role, ws.jd_raw)
                status = "LIVE"
            except Exception:
                # No provider exception text (which can include private input) enters logs or the UI.
                status = "LIVE_UNAVAILABLE_MANUAL_FALLBACK"
        from career.research_context import scope

        item, _ = save(
            self.db,
            self.user,
            ident,
            "CompanyResearchResult",
            {
                **result.model_dump(),
                "company": ws.company,
                "role": ws.role,
                "jd": {
                    "source_id": "USER_SUPPLIED_JD",
                    "published_at": None,
                    "deadline": None,
                    "raw_text_hash": sha256(ws.jd_raw.encode()).hexdigest(),
                },
                "mode": status,
                "scope": scope(result, status),
                "retrieved_at": now().isoformat(),
            },
        )
        if live and status == "LIVE_UNAVAILABLE_MANUAL_FALLBACK":
            from career.research_workspace import collect, jd_links

            for url in jd_links(ws.jd_raw):
                try:
                    item = collect(self, ident, {"research_id": item.id, "method": "URL", "url": url,
                                                 "category": "CURRENT_JD"})
                except ValueError:
                    # A blocked/inaccessible page never blocks JD-only work.
                    continue
        return item

    def analyze(self, ident: str, manual=None):
        ws = self.ws(ident)
        self.editable(ws)
        research = latest(self.db, self.user, ident, "CompanyResearchResult", required=False)
        if research is None:
            # Direct/manual analysis remains available, with a recorded JD-only
            # basis instead of silently suggesting that research was performed.
            research = self.research(ident)
        fresh(self.db, self.user, research)
        from career.research_workspace import analyzer_context, reviewed

        research_review = reviewed(self, ident, research, required=bool(research.data.get("sources")))
        if manual and research and "company_facts" not in manual:
            manual = {
                **manual,
                "company_facts": research.data.get("official_facts", [])
                + research.data.get("external_evidence", []),
                "company_inferences": research.data.get("inferences", []),
            }
        data = (
            OpportunityBrief.model_validate(manual).model_dump()
            if manual
            else self.ai(
                "opportunity",
                {
                    "company": ws.company,
                    "role": ws.role,
                    "jd_untrusted": ws.jd_raw,
                    "research": analyzer_context(research),
                    "hiring_context_review": research_review.data if research_review else {},
                },
                OpportunityBrief,
            )
        )
        if research_review:
            data["hiring_context"] = (
                "공개 근거에 따른 가설: " + research_review.data["hypothesis"]
                if research_review.data["mode"] == "HYPOTHESIS"
                else "채용 배경 미확인: " + research_review.data["limitation"]
            )
        valid_source_ids = {s["id"] for s in research.data.get("sources", [])} if research else set()
        if any(f["source_id"] not in valid_source_ids for f in data["company_facts"]):
            raise ValueError("회사 사실은 등록된 조사 출처와 연결해야 합니다.")
        if research.data.get("source_documents"):
            backed = {(fact["source_id"], fact["statement"]): fact for fact in
                      research.data["official_facts"] + research.data["external_evidence"]}
            if any((fact["source_id"], fact["statement"]) not in backed for fact in data["company_facts"]):
                raise ValueError("회사 사실은 원문 인용으로 정리한 조사 내용에서 선택해 주세요.")
            data["company_facts"] = [deepcopy(backed[(fact["source_id"], fact["statement"])])
                                     for fact in data["company_facts"]]
        from career.assessment import validate_opportunity

        validate_opportunity(data, valid_source_ids)
        item, _ = save(
            self.db,
            self.user,
            ident,
            "OpportunityBrief",
            data,
            deps=[research.id] + ([research_review.id] if research_review else []),
            sources=self.reference_sources("opportunity"),
            model="manual" if manual else self.current_model,
        )
        ws.state = "OPPORTUNITY_READY"
        return item

    def map_evidence(self, ident: str, manual=None, *, local_vector=None, local_profile_id=None):
        ws = self.ws(ident)
        self.editable(ws)
        brief = self.artifact(ident, "OpportunityBrief")
        query = " ".join(brief.data["actual_outputs"])
        try:
            candidates = search(
                self.db, self.user, query, embedder=configured_embedder(self.db), task_context=brief.data,
                local_vector=local_vector, local_profile_id=local_profile_id,
            )
        except ProviderUnavailable:
            candidates = search(self.db, self.user, query, task_context=brief.data,
                                local_vector=local_vector, local_profile_id=local_profile_id)
        from career.preparation import preparation_context

        preparation = preparation_context(self, ws, candidates)
        data = (
            EvidencePack.model_validate(manual).model_dump()
            if manual
            else self.ai(
                "evidence_mapper",
                {
                    "job_outputs": brief.data["actual_outputs"],
                    "main_skills": brief.data.get("main_skills", []),
                    "differentiators": brief.data.get("differentiators", []),
                    "output_importance": brief.data.get("output_importance", []),
                    "evidence_candidates": candidates,
                    "preparation": preparation["context"],
                    "task": "Classify output fit based on actual work. Link skill_focus/skill_name only to given JD skills. concrete_output/understandable_hook must be exact evidence quotes or empty. Retrieval priority alone is not Direct evidence.",
                },
                EvidencePack,
            )
        )
        sources = []
        for item in data["items"]:
            if item["job_output_id"] not in brief.data["actual_outputs"]:
                raise ValueError("공고에 없는 업무 산출물입니다.")
            evidence = owned(self.db, Evidence, self.user, item["evidence_id"])
            if evidence.status not in GOOD or evidence.kind == "EXPRESSION":
                raise ValueError("확인된 사실 근거만 연결할 수 있습니다.")
            sources.append(evidence.source_id)
            item["ownership"] = evidence.data.get("ownership", {})
            item["verification_status"] = evidence.status
            item["source_ids"] = [evidence.source_id]
            item["claim_boundaries"] = evidence.data.get("forbidden_claims", [])
        covered = {i["job_output_id"] for i in data["items"] if i["classification"] != "NO_EVIDENCE"}
        from career.resume_layout import rank_evidence

        rank_evidence(brief.data, data["items"], self.selected([i["evidence_id"] for i in data["items"]]))
        data["uncovered_outputs"] = [
            output for output in brief.data["actual_outputs"] if output not in covered
        ]
        semantic_candidates = [item for item in candidates if item.get("semantic_metadata")]
        data["retrieval_metadata"] = {
            "semantic_requested": local_vector is not None,
            "semantic_used": bool(semantic_candidates),
            "semantic_candidate_count": len(semantic_candidates),
            "profile_id": local_profile_id if local_vector is not None else None,
            "basis": "CANDIDATE_RETRIEVAL_NOT_FACT_OR_DIRECT_FIT_PROOF",
        }
        artifact, _ = save(
            self.db,
            self.user,
            ident,
            "EvidencePack",
            data,
            deps=[brief.id, *preparation["depends_on"]],
            sources=sorted(set(sources + preparation["source_ids"] + self.reference_sources("evidence_mapper"))),
            model="manual" if manual else self.current_model,
        )
        ws.state = "EVIDENCE_READY"
        return artifact

    def strategy(self, ident: str, manual=None):
        ws = self.ws(ident)
        self.editable(ws)
        opportunity = self.artifact(ident, "OpportunityBrief")
        pack = self.artifact(ident, "EvidencePack")
        assessment = latest(self.db, self.user, ident, "OpportunityAssessment", required=False)
        from career.experience_options import active_selection, selection_context

        selection = active_selection(self, ident, "strategy")
        from career.preparation import preparation_context

        preparation = preparation_context(self, ws, self.selected(list(dict.fromkeys(
            i["evidence_id"] for i in pack.data["items"] if i["classification"] != "NO_EVIDENCE"
        ))))
        if assessment and assessment.status not in {"ACTIVE", "LOCKED"}:
            raise ValueError("지원 가치·우선순위 평가를 현재 근거에 맞춰 다시 확인해 주세요.")
        decision = ws.data.get("opportunity_decision", {})
        current_decision = (
            decision.get("decision", "PENDING")
            if assessment and decision.get("artifact_id") == assessment.id
            else "PENDING"
        )
        data = (
            ApplicationBrief.model_validate(manual).model_dump()
            if manual
            else self.ai(
                "strategy",
                {
                    "opportunity": opportunity.data,
                    "evidence_pack": pack.data,
                    "opportunity_assessment": assessment.data if assessment else {},
                    "human_decision": current_decision,
                    "selected_experience": selection_context(selection),
                    "preparation": preparation["context"],
                },
                ApplicationBrief,
            )
        )
        if not data["assignment_statement"].strip():
            raise ValueError("맡길 수 있는 일을 구체적으로 정해 주세요.")
        data["selected_experience_id"] = selection.data["evidence_id"] if selection else None
        data["experience_selection_artifact_id"] = selection.id if selection else None
        item, _ = save(
            self.db,
            self.user,
            ident,
            "ApplicationBrief",
            data,
            deps=[opportunity.id, pack.id] + ([assessment.id] if assessment else [])
            + ([selection.id] if selection else []) + preparation["depends_on"],
            sources=sorted(set(self.reference_sources("strategy") + preparation["source_ids"]
                               + preparation["guidance_source_ids"])),
            model="manual" if manual else self.current_model,
        )
        ws.state = "WAITING_STRATEGY_APPROVAL"
        # Fast mode may skip approval only after deterministic escalation checks.
        conflicts = self.db.scalar(
            select(Fact).where(Fact.user_id == self.user, Fact.status == "CONFLICTED").limit(1)
        )
        if (
            ws.mode == "FAST"
            and selection is None
            and not self.reference_sources("strategy")
            and conflicts is None
            and not pack.data["uncovered_outputs"]
            and pack.data["items"]
            and not data["fatal_gaps"]
            and all(
                i["classification"] == "DIRECT"
                and i["ownership_strength"] == "STRONG"
                and isinstance(i.get("ownership"), dict)
                and i["ownership"].get("implementation", "UNKNOWN") != "UNKNOWN"
                for i in pack.data["items"]
            )
        ):
            self.approve_strategy(ident)
        return item

    def approve_strategy(self, ident: str):
        ws = self.ws(ident)
        self.editable(ws)
        if ws.state != "WAITING_STRATEGY_APPROVAL":
            raise ValueError("승인할 전략 제안이 없습니다.")
        item = self.artifact(ident, "ApplicationBrief")
        lock(self.db, self.user, item)
        feedback(self.db, self.user, item, "ACCEPT")
        ws.state = "STRATEGY_LOCKED"
        return item

    def add_question(self, ident: str, text: str, limit: int):
        ws = self.ws(ident)
        self.editable(ws)
        if not text.strip() or not 50 <= limit <= 20000:
            raise ValueError("문항과 글자 수 제한(50~20000)을 입력해 주세요.")
        question = {"id": uid(), "text": text, "limit": limit}
        ws.data = {**ws.data, "questions": [*ws.data.get("questions", []), question]}
        portfolio = latest(self.db, self.user, ident, "QuestionPortfolio", required=False)
        if portfolio:
            stale(self.db, self.user, [portfolio.id])
            portfolio.status = "STALE"
        elif len(ws.data["questions"]) > 1:
            for brief in self.db.scalars(select(Artifact).where(
                Artifact.user_id == self.user, Artifact.workspace_id == ident,
                Artifact.kind == "QuestionBrief", Artifact.status.in_(["ACTIVE", "LOCKED"]),
            )):
                stale(self.db, self.user, [brief.id])
                brief.status = "STALE"
        self.question_state(ident, question["id"], "NEW")
        if ws.state == "READY_TO_FREEZE":
            ws.state = "COMPOSING"
        return question

    def question(self, ident: str, qid: str):
        matches = [q for q in self.ws(ident).data.get("questions", []) if q["id"] == qid]
        if not matches:
            raise LookupError("문항을 찾을 수 없습니다.")
        return matches[0]

    def question_brief(self, ident: str, qid: str, manual=None):
        ws = self.ws(ident)
        self.editable(ws)
        strategy = self.artifact(ident, "ApplicationBrief")
        if strategy.status != "LOCKED":
            raise ValueError("전략 승인이 먼저 필요합니다.")
        from career.writing_plans import context as plan_context
        from career.writing_plans import persist as prepare_plan

        writing_plan = prepare_plan(self, ident, qid)
        question = self.question(ident, qid)
        pack = self.artifact(ident, "EvidencePack")
        from career.experience_options import active_selection, selection_context

        selection = active_selection(self, ident, qid, fallback=True)
        portfolio = latest(self.db, self.user, ident, "QuestionPortfolio", required=False)
        allocation = None
        if len(ws.data.get("questions", [])) > 1 and portfolio is None:
            raise ValueError("여러 문항은 역할과 메시지 후보를 배분하고 승인한 뒤 설계해 주세요.")
        if portfolio:
            fresh(self.db, self.user, portfolio)
            if portfolio.status != "LOCKED":
                raise ValueError("문항별 역할과 메시지 후보를 먼저 승인해 주세요.")
            allocation = next((item for item in portfolio.data["items"] if item["question_id"] == qid), None)
            if allocation is None:
                raise ValueError("새로 추가한 문항의 역할을 다시 배분해 주세요.")
        chosen_pack = pack.data
        if selection:
            chosen_id = selection.data["evidence_id"]
            chosen_pack = {**pack.data, "items": sorted(pack.data["items"], key=lambda i: i["evidence_id"] != chosen_id)}
            if allocation:
                allocation = {**allocation, "evidence_candidate_ids": list(dict.fromkeys(
                    [chosen_id, *allocation["evidence_candidate_ids"]])),
                              "primary_message_candidates": [],
                              "selection_note": "사용자가 경험을 변경했으므로 현재 근거로 메시지를 다시 구성합니다."}
        evidence = self.selected(list(dict.fromkeys(
            i["evidence_id"] for i in chosen_pack["items"] if i["classification"] != "NO_EVIDENCE"
        )))
        from career.preparation import preparation_context
        from career.retrieval import style_projection

        preparation = preparation_context(self, ws, evidence)
        styles = [style_projection(item) for item in search(
            self.db, self.user, question["text"], "EXPRESSION", limit=3
        )]
        from career.expressions import context as expression_context
        preferred = expression_context(self, "COVER", "", evidence, question=question["text"])
        data = (
            QuestionBrief.model_validate(manual).model_dump()
            if manual
            else self.ai(
                "question_brief",
                {
                    "question_id": qid,
                    "question": question,
                    "strategy": strategy.data,
                    "evidence_pack": chosen_pack,
                    "question_allocation": allocation,
                    "writing_plan": plan_context(writing_plan),
                    "selected_experience": selection_context(selection),
                    "evidence": evidence,
                    "preparation": preparation["context"],
                    "style_projections": preferred + styles,
                },
                QuestionBrief,
            )
        )
        if data["question_id"] != qid:
            raise ValueError("문항 ID가 다릅니다.")
        data["writing_plan_id"] = writing_plan.id
        if selection:
            if selection.data["evidence_id"] not in data["evidence_ids"]:
                raise ValueError("사용자가 선택한 경험으로 문항 메시지를 다시 구성해 주세요.")
            data["evidence_ids"] = list(dict.fromkeys([selection.data["evidence_id"], *data["evidence_ids"]]))
        data["selected_experience_id"] = selection.data["evidence_id"] if selection else None
        data["experience_selection_artifact_id"] = selection.id if selection else None
        if manual is None and os.getenv("JEV_SHADOW_ENABLED") == "1" and os.getenv("JEV_API_KEY"):
            try:
                decision = self.bounded_decision(
                    "question_type",
                    {"question": question["text"]},
                    [
                        "MOTIVATION",
                        "JOB_COMPETENCY",
                        "VALUES",
                        "COLLABORATION",
                        "CHALLENGE",
                        "STRENGTH_WEAKNESS",
                        "OTHER",
                    ],
                )
                data["question_type"] = decision.choice
            except Exception:
                self.db.add(
                    PromptRun(
                        user_id=self.user,
                        stage="shadow_check_unavailable",
                        provider="decision",
                        data={"task": "question_type"},
                    )
                )
        selected = {i["evidence_id"] for i in pack.data["items"] if i["classification"] != "NO_EVIDENCE"}
        if not set(data["evidence_ids"]) <= selected:
            raise ValueError("현재 근거 매핑에 포함된 근거를 선택해 주세요.")
        if data["value_scope"] == "MEASURED_BUSINESS_IMPACT" and not any(
            m["status"] in GOOD and m.get("measurement_context") == "PRODUCTION" and m.get("business_effect")
            for e in self.selected(data["evidence_ids"])
            for m in e["data"]["metric_ledger"]
        ):
            raise ValueError(
                "측정한 업무 성과는 실제 운영에서 확인된 업무 지표가 있어야 합니다. 적용 가능성으로 구분해 주세요."
            )
        item, _ = save(
            self.db,
            self.user,
            ident,
            "QuestionBrief",
            data,
            deps=[strategy.id, pack.id, writing_plan.id] + ([portfolio.id] if portfolio else [])
            + ([selection.id] if selection else []) + preparation["depends_on"],
            sources=sorted(set(self.reference_sources("question_brief") + preparation["source_ids"]
                               + preparation["guidance_source_ids"]
                               + [source for item in evidence for source in item["context_source_ids"]])),
            slot=qid,
            model="manual" if manual else self.current_model,
        )
        self.question_state(ident, qid, "WAITING_CLAIM_APPROVAL")
        ws.state = "COMPOSING"
        return item

    def approve_question(self, ident: str, qid: str):
        self.editable(self.ws(ident))
        item = self.artifact(ident, "QuestionBrief", qid)
        from career.claim_test import require_pass
        from career.portfolio import require_current

        require_current(self, ident, item)
        proof = require_pass(self, ident, qid, item)
        from career.writing_plans import approve as approve_plan

        approve_plan(self, ident, qid, item)
        lock(self.db, self.user, proof)
        lock(self.db, self.user, item)
        feedback(self.db, self.user, item, "ACCEPT")
        self.question_state(ident, qid, "BRIEF_LOCKED")
        return item

    def test_claim(self, ident: str, qid: str, manual=None, confirmed=False):
        from career.claim_test import run

        return run(self, ident, qid, manual, confirmed=confirmed)

    def selected(self, identifiers: list[str]):
        from career.project_boundaries import catalog as boundary_catalog
        from career.project_boundaries import projection as boundary_projection

        boundary_rules = boundary_catalog(self.db, self.user)
        result = []
        for ident in identifiers:
            e = owned(self.db, Evidence, self.user, ident)
            if e.status not in GOOD or e.kind == "EXPRESSION":
                raise ValueError("선택한 근거가 현재 유효하지 않습니다.")
            from career.models import Source

            if owned(self.db, Source, self.user, e.source_id).status not in GOOD:
                raise ValueError("선택 근거의 출처가 무효화되었습니다.")
            from career.entities import MetricRecord

            item = view(e)
            item["data"] = {
                **item["data"],
                "metric_ledger": [
                    {**m.data, "id": m.id, "status": m.status}
                    for m in self.db.scalars(
                        select(MetricRecord).where(
                            MetricRecord.user_id == self.user, MetricRecord.evidence_id == e.id
                        )
                    )
                ],
            }
            for metric in item["data"]["metric_ledger"]:
                if (
                    metric["status"] in GOOD
                    and owned(self.db, Source, self.user, metric["source_id"]).status not in GOOD
                ):
                    raise ValueError("선택 근거의 지표 출처가 무효화되었습니다.")
            from career.entities import ClaimBoundaryRecord, DecisionEpisodeRecord, OwnershipRecord

            context_sources = {e.source_id}
            item["data"].pop("project_boundary", None)
            if boundary := boundary_projection(self.db, self.user, e, rules=boundary_rules):
                item["data"]["project_boundary"] = boundary
                context_sources.add(boundary["source_id"])
            context_sources.update(m["source_id"] for m in item["data"]["metric_ledger"] if m["status"] in GOOD)
            for key, model in [("confirmed_decision_episodes", DecisionEpisodeRecord),
                               ("confirmed_ownership", OwnershipRecord),
                               ("confirmed_claim_boundaries", ClaimBoundaryRecord)]:
                records = []
                for record in self.db.scalars(select(model).where(
                    model.user_id == self.user, model.evidence_id == e.id, model.status.in_(GOOD)
                )):
                    if record.source_id and owned(self.db, Source, self.user, record.source_id).status in GOOD:
                        records.append({"id": record.id, "version": record.version,
                                        "status": record.status, "data": record.data})
                        context_sources.add(record.source_id)
                item["data"][key] = records
            item["context_source_ids"] = sorted(context_sources)
            result.append(item)
        return result

    def draft(self, ident: str, qid: str, manual=None):
        ws = self.ws(ident)
        self.editable(ws)
        brief = self.artifact(ident, "QuestionBrief", qid)
        strategy = self.artifact(ident, "ApplicationBrief")
        if brief.status != "LOCKED" or strategy.status != "LOCKED":
            raise ValueError("전략과 문항 메시지를 승인한 후 작성할 수 있습니다.")
        from career.claim_test import require_pass
        from career.portfolio import require_current

        require_current(self, ident, brief)
        proof = require_pass(self, ident, qid, brief)
        from career.writing_plans import context as plan_context
        from career.writing_plans import require_current as current_plan

        writing_plan = current_plan(self, ident, qid, brief)
        from career.experience_options import active_selection

        selection = active_selection(self, ident, qid, fallback=True)
        if selection and brief.data["evidence_ids"][0] != selection.data["evidence_id"]:
            raise ValueError("선택 경험과 문항 근거가 달라졌습니다. 경험을 다시 선택하고 메시지를 승인해 주세요.")
        evidence = self.selected(brief.data["evidence_ids"])
        context = compile_context("writer", strategy=strategy.data, brief=brief.data, evidence=evidence)
        context["actual_target_question"] = {
            **self.question(ident, qid), "company": ws.company, "role": ws.role,
            "counting_basis": "공백·줄바꿈 포함",
        }
        if writing_plan:
            context["writing_plan"] = plan_context(writing_plan)
        from career.rules import writing_rules

        rules = writing_rules(
            self.db, self.user, ws, brief.data["question_type"], [e["title"] for e in evidence]
        )
        context["verified_writing_guidance"] = rules
        from career.retrieval import style_projection

        context["style_projections"] = [
            style_projection(item)
            for item in search(self.db, self.user, self.question(ident, qid)["text"], "EXPRESSION", limit=3)
        ]
        from career.expressions import context as expression_context
        from career.expressions import usage as expression_usage

        preferred = expression_context(self, "COVER", brief.data["question_type"], evidence)
        context["style_projections"] = preferred + context["style_projections"]
        profile = canonical(self.db, self.user)
        context["canonical_profile"] = profile
        opportunity = self.artifact(ident, "OpportunityBrief")
        context["current_company_facts"] = [
            f for f in opportunity.data.get("company_facts", []) if f["freshness"] == "CURRENT"
        ]
        research = latest(self.db, self.user, ident, "CompanyResearchResult", required=False)
        fact_sources = {f["source_id"] for f in context["current_company_facts"]}
        context["company_sources"] = (
            [s for s in research.data.get("sources", []) if s["id"] in fact_sources] if research else []
        )
        context["company_claim_contract"] = "Company FACT claims must use exact current_company_facts statements and their company_source_ids; do not attach unrelated personal evidence or use company numbers as personal achievements."
        context["character_limit"] = self.question(ident, qid)["limit"]
        data = (
            Document.model_validate(manual).model_dump() if manual else self.ai("writer", context, Document)
        )
        old = latest(self.db, self.user, ident, "Draft", qid, required=False)
        if old and any(
            data["text"].count(span) < old.data["text"].count(span)
            for span in old.data.get("protected_spans", [])
        ):
            raise ValueError("재작성 결과가 보호된 문장을 바꿉니다. 부분 수정으로 진행해 주세요.")
        data["selected_evidence_ids"] = brief.data["evidence_ids"]
        data["protected_spans"] = old.data.get("protected_spans", []) if old else []
        data["revision_count"] = 0
        data["expression_usage"] = expression_usage(preferred) if manual is None else []
        self.validate_ledger(data, evidence)
        item, _ = save(
            self.db,
            self.user,
            ident,
            "Draft",
            data,
            deps=[brief.id, proof.id],
            sources=list(
                {e["source_id"] for e in evidence}
                | {source for e in evidence for source in e["context_source_ids"]}
                | {f["source_id"] for f in profile.values()}
                | {r["source_id"] for r in rules}
                | set(self.reference_sources("writer"))
            ),
            slot=qid,
            model="manual" if manual else self.current_model,
        )
        self.question_state(ident, qid, "DRAFTED")
        ws.state = "REVIEWING"
        return item

    def validate_ledger(self, document: dict, evidence: list[dict]):
        allowed = {e["id"] for e in evidence}
        profile = {f["id"]: f for f in canonical(self.db, self.user).values() if f["fact_type"] == "profile"}
        opportunity = self.artifact(self.current_workspace, "OpportunityBrief") if self.current_workspace else None
        company_facts = opportunity.data.get("company_facts", []) if opportunity else []
        research = latest(self.db, self.user, self.current_workspace, "CompanyResearchResult", required=False) if self.current_workspace else None
        company_sources = {s["id"] for s in research.data.get("sources", [])} if research else set()
        if not document["claims"]:
            raise ValueError("사실 주장과 근거를 연결한 ClaimLedger가 필요합니다.")
        for claim in document["claims"]:
            if claim["text"] not in document["text"]:
                raise ValueError("ClaimLedger 문장이 본문에 없습니다.")
            profile_ids = claim.get("profile_fact_ids", [])
            company_ids = claim.get("company_source_ids", [])
            if not (claim["evidence_ids"] or profile_ids or company_ids) or not set(claim["evidence_ids"]) <= allowed:
                raise ValueError("모든 주장은 선택 근거와 연결해야 합니다.")
            if company_ids and (
                claim["type"] != "FACT"
                or claim.get("metric_ids")
                or not set(company_ids) <= company_sources
                or any(
                    not any(f["source_id"] == source and f["freshness"] == "CURRENT" and f["statement"] == claim["text"] for f in company_facts)
                    for source in company_ids
                )
            ):
                raise ValueError("회사 사실은 현재 확인된 출처의 원문과 정확히 연결해 주세요. 개인 성과로 사용할 수 없습니다.")
            if profile_ids:
                if claim["type"] != "FACT" or not set(profile_ids) <= set(profile):
                    raise ValueError("현재 확인된 프로필 사실은 사실 문장에만 연결할 수 있습니다.")
                quotes = [profile[i]["value"].get("text", "") for i in profile_ids]
                if not all(
                    isinstance(quote, str) and quote.strip() and quote in document["text"] for quote in quotes
                ) or not any(claim["text"] in quote for quote in quotes):
                    raise ValueError("프로필 사실은 현재 원문과 정확하게 대조해 주세요.")
            supported_metrics = {
                m["id"]
                for e in evidence
                if e["id"] in claim["evidence_ids"]
                for m in e["data"].get("metric_ledger", [])
                if m.get("status") in GOOD
            }
            if not set(claim.get("metric_ids", [])) <= supported_metrics:
                raise ValueError("지표 주장은 선택 근거의 확인된 지표와 연결해야 합니다.")

    def review(self, ident: str, qid="", manual_verified=False, resume=False):
        ws = self.ws(ident)
        self.editable(ws)
        kind = "ResumeContent" if resume else "Draft"
        document = self.artifact(ident, kind, qid)
        evidence = self.selected(document.data["selected_evidence_ids"])
        issues: list[dict[str, Any]] = hard_qa(
            document.data["text"],
            evidence,
            document.data.get("character_budget", 10000) if resume else self.question(ident, qid)["limit"],
            profile=canonical(self.db, self.user),
            company_facts=self.artifact(ident, "OpportunityBrief").data.get("company_facts", []),
            document=document.data,
        )
        if resume:
            issues.extend(skimmability_qa(document.data["text"]))
        issues.extend(ledger_coverage(document.data))
        from career.project_boundaries import document_issues

        issues.extend(document_issues(document.data, evidence))
        for claim in document.data["claims"]:
            if claim["support"] != "SUPPORTED" or not claim["ownership_ok"]:
                issues.append({"code": "CLAIM_SUPPORT", "priority": "P0", "message": claim["text"]})
        followups = []
        from career.review_resolution import compile_tasks, tasks_for

        response_tasks = []
        if manual_verified:
            review_mode = "USER_VERIFIED"
            previous_review = latest(self.db, self.user, ident, "ResumeReview" if resume else "Review", qid, required=False)
            if previous_review and document.id in previous_review.depends_on:
                # Quick manual review cannot erase recorded unresolved AI concerns.
                response_tasks = tasks_for(previous_review)
                followups = previous_review.data.get("followups", [])
                for issue in previous_review.data["issues"]:
                    if issue not in issues:
                        issues.append(issue)
        else:
            from career.parallel_qa import run as parallel_review

            research = latest(self.db, self.user, ident, "CompanyResearchResult", required=False)
            fact, recruiter = parallel_review(
                self,
                [
                    (
                        "fact_reviewer",
                        {
                            "document": document.data,
                            "evidence": evidence,
                            "canonical_profile": canonical(self.db, self.user),
                            "company_facts": self.artifact(ident, "OpportunityBrief").data.get(
                                "company_facts", []
                            ),
                            "company_sources": research.data.get("sources", []) if research else [],
                        },
                        Review,
                    ),
                    (
                        "recruiter",
                        {
                            **compile_context(
                                "recruiter",
                                jd=ws.jd_raw,
                                question="이력서" if resume else self.question(ident, qid)["text"],
                                draft=document.data["text"],
                            ),
                            "document_domain": "RESUME" if resume else "COVER",
                        },
                        Review,
                    ),
                ],
            )
            assert fact is not None and recruiter is not None
            issues.extend(fact["issues"] + recruiter["issues"])
            followups.extend(fact["followups"] + recruiter["followups"])
            response_tasks = compile_tasks([("fact_reviewer", fact), ("recruiter", recruiter)])
            if (
                any(c["type"] in {"METRIC", "OWNERSHIP"} for c in document.data["claims"])
                or issues
                or self.reference_sources("writer")
            ):
                reverse = self.ai("reverse_interview", {
                    "document": document.data, "evidence": evidence, "jd": ws.jd_raw,
                    "question": "이력서" if resume else self.question(ident, qid)["text"],
                    "opportunity": self.artifact(ident, "OpportunityBrief").data,
                    "strategy": self.artifact(ident, "ApplicationBrief").data,
                    "document_domain": "RESUME" if resume else "COVER",
                }, Review)
                issues.extend(reverse["issues"])
                followups.extend(reverse["followups"])
                response_tasks.extend(compile_tasks([("reverse_interview", reverse)]))
            review_mode = "AI_REVIEWED"
            if os.getenv("JEV_SHADOW_ENABLED") == "1" and os.getenv("JEV_API_KEY"):
                checks = [
                    (
                        "role_noun_alignment",
                        ["aligned", "misaligned"],
                        "misaligned",
                        "ROLE_NOUN",
                        "P2",
                        "직무에서 기대하는 역할 명칭을 다시 확인하세요.",
                    ),
                    (
                        "direct_answer",
                        ["yes", "no"],
                        "no",
                        "DIRECT_ANSWER",
                        "P1",
                        "질문에 대한 직접적인 답을 앞부분에 배치하세요.",
                    ),
                    (
                        "jargon_overload",
                        ["yes", "no"],
                        "yes",
                        "JARGON",
                        "P2",
                        "기술 용어 나열을 줄이고 산출물과 판단을 먼저 보여 주세요.",
                    ),
                    (
                        "revision_routing",
                        ["revise", "accept"],
                        "revise",
                        "REVISION_ROUTE",
                        "P2",
                        "현재 검수 의견에 따라 수정 여부를 확인하세요.",
                    ),
                ]
                for task, options, flagged, code, priority, message in checks:
                    try:
                        decision = self.bounded_decision(
                            task,
                            {
                                "role": ws.role,
                                "question": "이력서" if resume else self.question(ident, qid)["text"],
                                "document": document.data["text"],
                                "issues": issues,
                            },
                            options,
                        )
                        if decision.choice == flagged:
                            issues.append({"priority": priority, "code": code, "message": message})
                    except Exception:
                        # Optional bounded checks never break the established reviewer flow.
                        self.db.add(
                            PromptRun(
                                user_id=self.user,
                                stage="shadow_check_unavailable",
                                provider="decision",
                                data={"task": task},
                            )
                        )
        review, _ = save(
            self.db,
            self.user,
            ident,
            "ResumeReview" if resume else "Review",
            {
                "issues": issues,
                "followups": followups,
                "mode": review_mode,
                "document_version": document.version,
                "response_tasks": response_tasks,
            },
            deps=[document.id],
            sources=sorted(set(self.reference_sources("fact_reviewer")
                               + self.reference_sources("recruiter", "RESUME" if resume else "COVER")
                               + self.reference_sources("reverse_interview", "RESUME" if resume else "COVER"))),
            slot=qid,
            model="manual" if manual_verified else self.current_model,
        )
        if resume:
            self.resume_state(
                ident, "REVIEWED" if response_tasks or any(i["priority"] in {"P0", "P1"} for i in issues) else "FINAL_READY"
            )
        else:
            self.question_state(
                ident,
                qid,
                "QA_FAILED" if response_tasks or any(i["priority"] in {"P0", "P1"} for i in issues) else "FINAL_READY",
            )
        ws.state = "REVIEWING"
        return review

    def answer_review(self, ident: str, qid: str, payload: dict, resume=False, manual=False):
        from career.review_resolution import respond

        return respond(self, ident, qid, payload, resume, manual=manual)

    def patch_document(
        self,
        ident: str,
        qid: str,
        old_text: str,
        new_text: str,
        protected=None,
        automatic=False,
        resume=False,
    ):
        self.editable(self.ws(ident))
        kind = "ResumeContent" if resume else "Draft"
        old = self.artifact(ident, kind, qid)
        data = deepcopy(old.data)
        if automatic and data.get("revision_count", 0) >= 2:
            raise ValueError("자동 수정은 2회까지 가능합니다. 직접 수정해 주세요.")
        if old_text and data["text"].count(old_text) != 1:
            raise ValueError("수정할 원문이 정확히 한 곳에 있어야 합니다.")
        candidate = data["text"].replace(old_text, new_text, 1) if old_text else data["text"]
        if any(candidate.count(span) < data["text"].count(span) for span in data.get("protected_spans", [])):
            raise ValueError("보호된 문장을 바꾸는 수정입니다.")
        if protected is not None and any(span not in candidate or not span for span in protected):
            raise ValueError("본문에 있는 문장을 보호 대상으로 선택해 주세요.")
        data["text"] = candidate
        data["protected_spans"] = data.get("protected_spans", []) if protected is None else protected
        data["revision_count"] = data.get("revision_count", 0) + int(automatic)
        if old_text and old_text != new_text:
            # A changed draft must have its ledger refreshed, never inherit automatic support.
            data["claims"] = [
                {
                    "text": candidate,
                    "type": "FACT",
                    "evidence_ids": data["selected_evidence_ids"],
                    "metric_ids": [],
                    "support": "NEEDS_REVIEW",
                    "ownership_ok": False,
                }
            ]
        if resume:
            data.update(legacy_sections(data))
        item, changed = save(
            self.db, self.user, ident, kind, data, deps=old.depends_on, sources=old.source_ids, slot=qid
        )
        if resume:
            self.resume_state(ident, "CONTENT_DRAFTED")
        else:
            self.question_state(ident, qid, "DRAFTED")
        feedback(self.db, self.user, item, "EDIT", old.data, data)
        self.ws(ident).state = "REVIEWING"
        return {"artifact": view(item), "stale_artifacts": changed}

    def update_ledger(self, ident: str, qid: str, claims: list[dict], resume=False):
        self.editable(self.ws(ident))
        kind = "ResumeContent" if resume else "Draft"
        old = self.artifact(ident, kind, qid)
        document = Document.model_validate({"text": old.data["text"], "claims": claims}).model_dump()
        self.validate_ledger(document, self.selected(old.data["selected_evidence_ids"]))
        if resume:
            document.update(legacy_sections(document))
        item, _ = save(
            self.db,
            self.user,
            ident,
            kind,
            {**old.data, **document},
            deps=old.depends_on,
            sources=old.source_ids,
            slot=qid,
        )
        return item

    def revise(self, ident: str, qid: str, resume=False):
        self.editable(self.ws(ident))
        document = self.artifact(ident, "ResumeContent" if resume else "Draft", qid)
        review = self.artifact(ident, "ResumeReview" if resume else "Review", qid)
        if document.data.get("revision_count", 0) >= 2:
            raise ValueError("자동 수정은 2회까지 가능합니다. 직접 수정해 주세요.")
        if not review.data["issues"]:
            raise ValueError("수정할 검수 의견이 없습니다.")
        evidence = self.selected(document.data["selected_evidence_ids"])
        patch = self.ai(
            "issue_patch_compression",
            {
                "document": document.data,
                "issues": review.data["issues"],
                "protected_spans": document.data.get("protected_spans", []),
                "evidence": evidence,
                "character_limit": document.data.get("character_budget", 10000)
                if resume else self.question(ident, qid)["limit"],
                "document_domain": "RESUME" if resume else "COVER",
                "preserve": ["질문에 대한 답", "핵심 판단", "근거", "수행 범위", "회사 근거"],
                "remove_first": ["기술 스택 나열", "반복", "일반론", "수식어"],
            },
            Patch,
        )
        if not patch["old_text"]:
            raise ValueError("수정할 원문이 없는 응답입니다.")
        if not set(patch["issue_codes"]) <= {i["code"] for i in review.data["issues"]}:
            raise ValueError("현재 검수 의견에 없는 내용을 수정하려 합니다.")
        from career.human_review import propose_patch

        return propose_patch(self, ident, qid, patch, resume=resume, review_id=review.id)

    def apply_revision(self, ident: str, qid: str, patch: dict, resume=False):
        result = self.patch_document(
            ident, qid, patch["old_text"], patch["new_text"], automatic=True, resume=resume
        )
        updated = self.update_ledger(ident, qid, patch["claims"], resume=resume)
        result["artifact"] = view(updated)
        return result

    def final_lock(self, ident: str, qid="", resume=False):
        self.editable(self.ws(ident))
        document = self.artifact(ident, "ResumeContent" if resume else "Draft", qid)
        review = self.artifact(ident, "ResumeReview" if resume else "Review", qid)
        from career.project_boundaries import document_issues

        if document_issues(document.data, self.selected(document.data["selected_evidence_ids"])):
            raise ValueError("프로젝트 표현 제한과 충돌하는 문장을 먼저 수정하고 검수해 주세요.")
        if document.id not in review.depends_on or any(
            i["priority"] in {"P0", "P1"} for i in review.data["issues"]
        ):
            raise ValueError("현재 버전의 중대한 검수 문제를 먼저 해결해 주세요.")
        from career.review_resolution import require_resolved

        require_resolved(self, ident, review, document, locking=True)
        if resume and self.reference_sources("resume_writer"):
            from career.resume_master import require_file_qa

            require_file_qa(self, document)
        lock(self.db, self.user, document)
        lock(self.db, self.user, review)
        feedback(self.db, self.user, document, "ACCEPT")
        if resume:
            self.resume_state(ident, "FINAL_LOCKED")
        else:
            self.question_state(ident, qid, "FINAL_LOCKED")
        return document

    def resume(self, ident: str, manual=None, page_budget=None):
        ws = self.ws(ident)
        self.editable(ws)
        old = latest(self.db, self.user, ident, "ResumeContent", required=False)
        if page_budget is None:
            page_budget = old.data.get("page_budget", 1) if old else 1
        if page_budget not in (1, 2, "MASTER"):
            raise ValueError("분량은 1페이지, 2페이지, 마스터 중에서 선택해 주세요.")
        strategy = self.artifact(ident, "ApplicationBrief")
        if strategy.status != "LOCKED":
            raise ValueError("전략 승인 후 이력서를 작성해 주세요.")
        pack = self.artifact(ident, "EvidencePack")
        opportunity = self.artifact(ident, "OpportunityBrief")
        from career.resume_layout import ORDER, arrange, rank_evidence, section_budgets

        candidates = list(
            dict.fromkeys(
                i["evidence_id"] for i in pack.data["items"] if i["classification"] != "NO_EVIDENCE"
            )
        )
        ranking = rank_evidence(opportunity.data, pack.data["items"], self.selected(candidates))
        from career.experience_options import active_selection, selection_context

        selection = active_selection(self, ident, "resume", fallback=True)
        if selection:
            ranking.sort(key=lambda row: row["evidence_id"] != selection.data["evidence_id"])
            ranking = [{**row, "rank": index + 1} for index, row in enumerate(ranking)]
        selected = [item["evidence_id"] for item in ranking]
        evidence = self.selected(selected)
        from career.resume_master import master_context

        master, master_id = master_context(self, selected)
        from career.rules import writing_rules

        rules = writing_rules(self.db, self.user, ws, "RESUME", [e["title"] for e in evidence])
        from career.expressions import context as expression_context
        from career.expressions import usage as expression_usage

        preferred = expression_context(self, "RESUME", "RESUME", evidence)
        brief_data = ResumeBrief.model_validate(
            {
                "target_role": ws.role,
                "top_capabilities": [strategy.data["main_skill_message"]],
                "project_order": [e["title"] for e in evidence],
                "selected_evidence_ids": selected,
                "page_budget": page_budget,
                "bullet_intents": ["성과 또는 산출물 → 행동 → 필요한 판단 근거"],
                "main_skills": opportunity.data.get("main_skills", []),
                "differentiators": opportunity.data.get("differentiators", []),
                "evidence_ranking": ranking,
                "section_order": ORDER,
                "section_budget": section_budgets(page_budget),
                "selected_experience_id": selection.data["evidence_id"] if selection else None,
                "experience_selection_artifact_id": selection.id if selection else None,
            }
        ).model_dump()
        if manual and "sections" not in manual:
            data = Document.model_validate(manual).model_dump()
            data.update(legacy_sections(data))
        else:
            content = (
                ResumeContent.model_validate(manual)
                if manual
                else ResumeContent.model_validate(
                    self.ai(
                        "resume_writer",
                        {
                            "strategy": strategy.data,
                            "resume_brief": brief_data,
                            "evidence": evidence,
                            "verified_writing_guidance": rules,
                            "canonical_profile": canonical(self.db, self.user),
                            "document_domain": "RESUME",
                            "canonical_master": master,
                            "selected_experience": selection_context(selection),
                            "style_projections": preferred,
                        },
                        ResumeContent,
                    )
                )
            )
            if manual:
                brief_data["section_order"] = [s.kind for s in content.sections]
                brief_data["section_budget"] = {
                    k: v for k, v in brief_data["section_budget"].items() if k in brief_data["section_order"]
                }
            content = arrange(content, brief_data, preserve_order=bool(manual))
            data = structured_document(content, set(selected), profile=canonical(self.db, self.user))
        self.validate_ledger(data, evidence)
        protected = old.data.get("protected_spans", []) if old else []
        if old and any(data["text"].count(span) < old.data["text"].count(span) for span in protected):
            raise ValueError("재작성 결과가 보호된 문장을 바꿉니다. 부분 수정으로 진행해 주세요.")
        brief, _ = save(
            self.db,
            self.user,
            ident,
            "ResumeBrief",
            brief_data,
            deps=[strategy.id, pack.id] + ([master_id] if master_id else [])
            + ([selection.id] if selection else []),
        )
        data.update({"selected_evidence_ids": selected, "protected_spans": protected, "revision_count": 0})
        data["expression_usage"] = expression_usage(preferred) if manual is None else []
        data["character_budget"] = {1: 3500, 2: 7000, "MASTER": 20000}[page_budget]
        data["page_budget"] = page_budget
        item, _ = save(
            self.db,
            self.user,
            ident,
            "ResumeContent",
            data,
            deps=[brief.id],
            sources=list(
                {e["source_id"] for e in evidence}
                | {source for e in evidence for source in e["context_source_ids"]}
                | {r["source_id"] for r in rules}
                | {f["source_id"] for f in canonical(self.db, self.user).values()}
                | set(self.reference_sources("resume_writer"))
            ),
            model="manual" if manual else self.current_model,
        )
        ws.data = {**ws.data, "resume_requested": True}
        self.resume_state(ident, "CONTENT_DRAFTED")
        ws.state = "REVIEWING"
        return item

    def review_portfolio(self, ident: str, *, manual_verified=False):
        from career.portfolio_review import run

        return run(self, ident, manual_verified=manual_verified)

    def prepare_after_lock(self, ident: str):
        from career.final_decision import require_pass as require_final_review
        from career.portfolio_review import current

        require_final_review(self, ident)
        whole = current(self, ident)
        if whole is None:
            whole = self.review_portfolio(ident)
            if any(i["priority"] in {"P0", "P1"} for i in whole.data["issues"]):
                return {
                    "interpreted_action": "전체 문서 검수",
                    "patched_artifacts": [whole.id],
                    "stale_artifacts": [],
                    "message": "문서 간 검수 결과를 저장했습니다. 충돌·반복 문제를 먼저 수정해 주세요.",
                }
        elif any(i["priority"] in {"P0", "P1"} for i in whole.data["issues"]):
            raise ValueError("전체 문서 검수의 충돌·반복 문제를 먼저 수정해 주세요.")
        return self.ready(ident)

    def ready(self, ident: str):
        ws = self.ws(ident)
        self.editable(ws)
        self.artifact(ident, "ApplicationBrief")
        messages = []
        documents = []
        for q in ws.data.get("questions", []):
            brief = self.artifact(ident, "QuestionBrief", q["id"])
            from career.claim_test import require_pass
            from career.portfolio import require_current

            require_current(self, ident, brief)
            require_pass(self, ident, q["id"], brief)
            messages.append(brief.data["primary_message"].strip())
            document = self.artifact(ident, "Draft", q["id"])
            review = self.artifact(ident, "Review", q["id"])
            if document.status != "LOCKED" or review.status != "LOCKED":
                raise ValueError("모든 문항의 현재 본문과 검수 결과를 최종 잠금해 주세요.")
            from career.review_resolution import require_resolved

            require_resolved(self, ident, review, document)
            documents.append(document)
        if len(messages) != len(set(messages)):
            raise ValueError("문항 간 핵심 메시지가 중복됩니다. 서로 다른 역할을 정해 주세요.")
        if ws.data.get("resume_requested"):
            resume = self.artifact(ident, "ResumeContent")
            review = self.artifact(ident, "ResumeReview")
            if resume.status != "LOCKED" or review.status != "LOCKED":
                raise ValueError("이력서 본문과 검수 결과를 최종 잠금해 주세요.")
            from career.review_resolution import require_resolved

            require_resolved(self, ident, review, resume)
            documents.append(resume)
        if not documents:
            raise ValueError("최종 잠금된 문서가 필요합니다.")
        for document in documents:
            self.validate_ledger(document.data, self.selected(document.data["selected_evidence_ids"]))
        from career.final_decision import require_pass as require_final_review

        require_final_review(self, ident)
        from career.portfolio_review import current

        portfolio_review = current(self, ident) or self.review_portfolio(ident)
        portfolio = portfolio_review.data["issues"]
        if any(issue["priority"] in {"P0", "P1"} for issue in portfolio):
            raise ValueError(
                "문서 간 검수에서 충돌이 발견되었습니다: "
                + "; ".join(i["message"] for i in portfolio if i["priority"] in {"P0", "P1"})
            )
        ws.state = "READY_TO_FREEZE"
        return {"state": ws.state, "document_ids": [d.id for d in documents]}

    def freeze(self, ident: str):
        ws = self.ws(ident)
        if ws.state != "READY_TO_FREEZE":
            raise ValueError("검수와 최종 잠금을 먼저 완료해 주세요.")
        self.ready(ident)
        artifacts = [
            a
            for a in self.db.scalars(
                select(Artifact).where(Artifact.user_id == self.user, Artifact.workspace_id == ident)
            )
            if a.status in {"ACTIVE", "LOCKED"}
        ]
        evidence_ids = {e for a in artifacts for e in a.data.get("selected_evidence_ids", [])}
        evidence = self.selected(list(evidence_ids))
        data = {
            "company": ws.company,
            "role": ws.role,
            "jd": ws.jd_raw,
            "frozen_at": now().isoformat(),
            "submitted_at": None,
            "artifacts": [{**view(a), "created_at": a.created_at.isoformat()} for a in artifacts],
            "evidence": [{**e, "created_at": e["created_at"].isoformat()} for e in evidence],
        }
        opportunity = self.artifact(ident, "OpportunityBrief")
        strategy = self.artifact(ident, "ApplicationBrief")
        resume = latest(self.db, self.user, ident, "ResumeContent", required=False)
        answers = []
        claims = []
        for question in ws.data.get("questions", []):
            document = self.artifact(ident, "Draft", question["id"])
            brief = self.artifact(ident, "QuestionBrief", question["id"])
            answers.append(
                {
                    **question,
                    "answer": document.data["text"],
                    "draft_version": document.version,
                    "question_brief_version": brief.version,
                    "evidence_ids": document.data["selected_evidence_ids"],
                }
            )
            claims.extend(document.data["claims"])
        if resume:
            claims.extend(resume.data["claims"])
        profile = canonical(self.db, self.user)
        data.update(
            {
                "opportunity_version": opportunity.version,
                "application_brief_version": strategy.version,
                "resume_version": resume.version if resume else None,
                "cover_letter_answers": answers,
                "claim_ledger": {"claims": claims},
                "known_gaps": strategy.data["fatal_gaps"],
                "profile": {k: {**v, "created_at": v["created_at"].isoformat()} for k, v in profile.items()},
            }
        )
        bundle, _ = save(self.db, self.user, ident, "SubmissionBundle", data)
        bundle.status = "LOCKED"
        ws.state = "SUBMISSION_FROZEN"
        ws.data = {**ws.data, "submission_bundle_id": bundle.id}
        return bundle

    def confirm_submission(self, ident: str, confirmed: bool):
        ws = self.ws(ident)
        if not confirmed or ws.state != "SUBMISSION_FROZEN":
            raise ValueError("제출 보관본을 만든 후 실제 제출 완료를 명시적으로 확인해 주세요.")
        timestamp = now().isoformat()
        from career.projections import SubmissionSnapshot

        snapshot = self.db.scalar(
            select(SubmissionSnapshot).where(
                SubmissionSnapshot.user_id == self.user, SubmissionSnapshot.workspace_id == ident
            )
        )
        if snapshot:
            from datetime import datetime

            snapshot.submitted_at = datetime.fromisoformat(timestamp)
        ws.state = "SUBMITTED"
        ws.data = {**ws.data, "submitted_at": timestamp}
        self.db.add(
            Record(
                user_id=self.user,
                kind="SUBMISSION_CONFIRMATION",
                data={
                    "workspace_id": ident,
                    "bundle_id": ws.data["submission_bundle_id"],
                    "submitted_at": timestamp,
                },
            )
        )
        return {"state": ws.state, "submitted_at": timestamp}

    def close_application(self, ident: str, confirmed: bool, reason=""):
        ws = self.ws(ident)
        if not confirmed:
            raise ValueError("지원 추적을 종료할지 직접 확인해 주세요.")
        if not isinstance(reason, str) or len(reason) > 1000:
            raise ValueError("종료 메모는 1000자 이내로 입력해 주세요.")
        if ws.state == "CLOSED":
            if ws.data.get("closure_reason", "") != reason.strip():
                raise ValueError("이미 종료된 지원입니다. 보관된 종료 기록을 확인해 주세요.")
            return {
                "state": ws.state,
                "closed_at": ws.data["closed_at"],
                "closure_reason": ws.data.get("closure_reason", ""),
            }
        if ws.state != "SUBMITTED" or not ws.data.get("submitted_at"):
            raise ValueError("실제 제출을 확인한 지원만 추적 종료할 수 있습니다.")
        bundle = self.artifact(ident, "SubmissionBundle")
        timestamp = now().isoformat()
        reason = reason.strip()
        ws.state = "CLOSED"
        ws.data = {**ws.data, "closed_at": timestamp, "closure_reason": reason}
        self.db.add(
            Record(
                user_id=self.user,
                kind="ApplicationClosure",
                data={
                    "workspace_id": ident,
                    "bundle_id": bundle.id,
                    "previous_state": "SUBMITTED",
                    "submitted_at": ws.data["submitted_at"],
                    "closed_at": timestamp,
                    "reason": reason,
                    "confirmed": True,
                },
            )
        )
        return {"state": ws.state, "closed_at": timestamp, "closure_reason": reason}

    def handoff(self, ident: str):
        bundle = self.artifact(ident, "SubmissionBundle")
        from career.interview_defense import build_handoff

        data = build_handoff(bundle.data, bundle.id)
        data["historical_source_ids"] = list({e["source_id"] for e in bundle.data["evidence"]})
        from career.models import Source

        data["provenance_warnings"] = [
            source_id
            for source_id in data["historical_source_ids"]
            if owned(self.db, Source, self.user, source_id).status not in GOOD
        ]
        item, _ = save(
            self.db,
            self.user,
            ident,
            "InterviewHandoff",
            data,
            deps=[bundle.id],
            sources=self.reference_sources("reverse_interview"),
        )
        return item

    def outcome(self, ident: str, result: str, notes=""):
        self.ws(ident)
        allowed = {
            "DOCUMENT_PASS",
            "DOCUMENT_FAIL",
            "CODING_PASS",
            "CODING_FAIL",
            "ASSESSMENT_PASS",
            "ASSESSMENT_FAIL",
            "INTERVIEW_PASS",
            "INTERVIEW_FAIL",
            "FINAL_OFFER",
            "WITHDRAWN",
            "UNKNOWN",
        }
        if result not in allowed:
            raise ValueError("지원하지 않는 전형 결과입니다.")
        item = Record(
            user_id=self.user,
            kind="SelectionOutcome",
            data={"workspace_id": ident, "result": result, "notes": notes, "date": now().isoformat()},
        )
        self.db.add(item)
        self.db.flush()
        from career.projections import SelectionOutcome

        self.db.add(
            SelectionOutcome(
                id=item.id,
                user_id=self.user,
                workspace_id=ident,
                stage=result.split("_")[0],
                result=result,
                notes=notes,
            )
        )
        return item

    def postmortem(self, ident: str, draft_hypotheses=False):
        ws = self.ws(ident)
        rows = [
            r
            for r in self.db.scalars(
                select(Record)
                .where(Record.user_id == self.user, Record.kind == "SelectionOutcome")
                .order_by(Record.created_at, Record.id)
            )
            if r.data["workspace_id"] == ident
        ]
        if not rows:
            raise ValueError("전형 결과를 먼저 등록해 주세요.")
        result = rows[-1].data["result"]
        data = {
            "result": result,
            "confidence": "LOW",
            "attribution_scope": result.split("_")[0],
            "observation": "결과만으로 문장이나 전략의 효과를 단정할 수 없습니다.",
            "writing_rule_updated": False,
            "rule_status": "CANDIDATE_ONLY",
            "supporting_outcome_id": rows[-1].id,
        }
        scope = result.split("_")[0]
        notes = rows[-1].data.get("notes", "")
        bundle = latest(self.db, self.user, ident, "SubmissionBundle", required=False)
        if bundle:
            snapshot_artifacts = bundle.data.get("artifacts", [])
            snapshot_evidence = bundle.data.get("evidence", [])
            historical_jd = bundle.data.get("jd", "")
            dependency_ids = [bundle.id]
            snapshot_mode = "EXACT_FROZEN_SUBMISSION"
        else:
            current = list(
                self.db.scalars(
                    select(Artifact).where(
                        Artifact.user_id == self.user,
                        Artifact.workspace_id == ident,
                        Artifact.status.in_(["ACTIVE", "LOCKED"]),
                        Artifact.kind.notin_(["Postmortem", "InterviewHandoff"]),
                    )
                )
            )
            snapshot_artifacts = [view(a) for a in current]
            snapshot_evidence = []
            historical_jd = ws.jd_raw
            dependency_ids = [a.id for a in current]
            snapshot_mode = "CURRENT_RECORDS_SUBMISSION_NOT_RECONSTRUCTABLE"
        artifact_data = {a["kind"]: a["data"] for a in snapshot_artifacts if not a.get("slot")}
        opportunity = artifact_data.get("OpportunityBrief", {})
        strategy = artifact_data.get("ApplicationBrief", {})
        pack = artifact_data.get("EvidencePack", {})
        if not bundle:
            for evidence_id in dict.fromkeys(i["evidence_id"] for i in pack.get("items", [])):
                evidence = owned(self.db, Evidence, self.user, evidence_id)
                snapshot_evidence.append(
                    {
                        "id": evidence.id,
                        "title": evidence.title,
                        "body": evidence.body,
                        "source_id": evidence.source_id,
                        "status": evidence.status,
                        "data": evidence.data,
                    }
                )
        output_map = [
            {
                "output": output,
                "evidence": [i for i in pack.get("items", []) if i["job_output_id"] == output],
                "uncovered": output in pack.get("uncovered_outputs", []),
            }
            for output in opportunity.get("actual_outputs", [])
        ]
        claim_map = [
            {
                "document_id": a["id"],
                "document_version": a["version"],
                "question_id": a.get("slot", ""),
                "claim": claim,
                "output_relations": [
                    i for i in pack.get("items", []) if i["evidence_id"] in claim.get("evidence_ids", [])
                ],
            }
            for a in snapshot_artifacts
            if a["kind"] in {"Draft", "ResumeContent"}
            for claim in a["data"].get("claims", [])
        ]
        supporting_ids = list(
            dict.fromkeys([a["id"] for a in snapshot_artifacts] + ([bundle.id] if bundle else []))
        )
        observations = []
        if pack.get("uncovered_outputs"):
            observations.append(
                {
                    "type": "MAIN_SKILL_COVERAGE",
                    "observation": "당시 경험 연결에서 미충족 업무가 기록되어 있습니다: "
                    + "; ".join(pack["uncovered_outputs"]),
                }
            )
        if strategy.get("fatal_gaps"):
            observations.append(
                {
                    "type": "KNOWN_GAP",
                    "observation": "당시 전략에 이미 기록된 공백입니다: " + "; ".join(strategy["fatal_gaps"]),
                }
            )
        adjacent_claims = [
            c
            for c in claim_map
            if c["output_relations"]
            and not any(i["classification"] == "DIRECT" for i in c["output_relations"])
        ]
        if adjacent_claims:
            observations.append(
                {
                    "type": "ADJACENT_CLAIM_DEFENSE",
                    "observation": f"당시 문서 주장 중 {len(adjacent_claims)}개는 직접 경험으로 연결되지 않았습니다. 면접에서 적용 범위를 대조해야 합니다.",
                }
            )
        observations.append(
            {
                "type": scope,
                "observation": "사용자가 남긴 전형 메모: " + notes
                if notes
                else "전형 결과 외의 원인은 확인되지 않았습니다.",
            }
        )
        data.update(
            {
                "known_reason": None,
                "user_notes": notes,
                "notes_authority": "USER_REPORTED_NOT_VERIFIED_CAUSE",
                "reconstruction_mode": snapshot_mode,
                "reconstruction_warning": "실제 제출본이 없어 현재 기록으로만 대조했습니다."
                if not bundle
                else "",
                "supporting_artifact_ids": supporting_ids,
                "historical_jd": historical_jd,
                "reverse_mapping": {
                    "job_outputs": output_map,
                    "claims": claim_map,
                    "main_skill_message": strategy.get("main_skill_message", ""),
                    "differentiator_message": strategy.get("differentiator_message", ""),
                    "positioning": strategy.get("positioning", ""),
                    "known_gaps": strategy.get("fatal_gaps", []),
                    "evidence": snapshot_evidence,
                },
                "hypotheses": [
                    {
                        **observation,
                        "confidence": "LOW",
                        "attribution_scope": scope,
                        "supporting_artifact_ids": supporting_ids,
                        "validation_needed": "평가 피드백이나 당시 제출본·전형 기록과 대조해야 합니다.",
                    }
                    for observation in observations
                ],
                "candidate_rules": [],
            }
        )
        data["hypothesis_mode"] = "RECORDED_OBSERVATIONS"
        if draft_hypotheses:
            from career.postmortem_hypotheses import draft

            self.input_artifact_ids.update(supporting_ids)
            data["hypotheses"].extend(draft(self, data))
            data["hypothesis_mode"] = "MODEL_DRAFT_WITH_RECORDED_OBSERVATIONS"
        if scope == "DOCUMENT" and notes:
            data["candidate_rules"] = [
                {
                    "scope_type": "COMPANY",
                    "scope_value": self.ws(ident).company,
                    "status": "CANDIDATE",
                    "rule": "같은 전형을 준비할 때 받은 피드백을 검토하세요: " + notes,
                    "source_case_ids": [rows[-1].id],
                }
            ]
            from career.domain import save_entity
            from career.entities import WritingRuleRecord
            from career.truth import register_source

            source, _ = register_source(
                self.db, self.user, "outcomes/" + rows[-1].id, notes, "USER_OBSERVATION"
            )
            existing = self.db.scalar(
                select(WritingRuleRecord).where(
                    WritingRuleRecord.user_id == self.user, WritingRuleRecord.source_id == source.id
                )
            )
            candidate = existing or save_entity(
                self.db,
                self.user,
                "WritingRule",
                {
                    **data["candidate_rules"][0],
                    "source_id": source.id,
                    "rule_type": "OUTCOME_FEEDBACK",
                },
            )
            data["candidate_rule_ids"] = [candidate.id]
        item, _ = save(
            self.db,
            self.user,
            ident,
            "Postmortem",
            data,
            deps=dependency_ids,
            sources=self.reference_sources("postmortem"),
        )
        return item

    def command(self, ident: str, text: str, qid="", evidence_id="", resume=False):
        ws = self.ws(ident)
        patched, changed = [], []
        action = text.strip()
        if action == "전체 문서 검수":
            item = self.review_portfolio(ident)
            return {
                "interpreted_action": action,
                "patched_artifacts": [item.id],
                "stale_artifacts": [],
                "message": "현재 문서의 사실·수치·수행 범위와 반복 검사 결과를 저장했습니다.",
            }
        if action == "제출했다":
            return self.confirm_submission(ident, True)
        if action == "ㄱㄱ":
            if resume:
                document = latest(self.db, self.user, ident, "ResumeContent", required=False)
                current_review = latest(self.db, self.user, ident, "ResumeReview", required=False)
                if document is None or document.status not in {"ACTIVE", "LOCKED"}:
                    item = self.resume(ident)
                elif current_review is None or current_review.status not in {"ACTIVE", "LOCKED"}:
                    item = self.review(ident, resume=True)
                elif any(i["priority"] in {"P0", "P1"} for i in current_review.data["issues"]):
                    raise ValueError("이력서 검수 문제를 먼저 수정해 주세요.")
                elif document.status == "LOCKED":
                    return self.prepare_after_lock(ident)
                else:
                    item = self.final_lock(ident, resume=True)
            elif ws.state == "CREATED" or (ws.state == "NEED_USER_ACTION" and (
                (previous_analysis := latest(self.db, self.user, ident, "OpportunityBrief", required=False)) is None
                or previous_analysis.status not in {"ACTIVE", "LOCKED"}
            )):
                research = latest(self.db, self.user, ident, "CompanyResearchResult", required=False)
                if research is None:
                    item = self.research(ident, live=True)
                else:
                    from career.research_workspace import reviewed

                    reviewed(self, ident, research, required=True)
                    item = self.analyze(ident)
            elif ws.state == "OPPORTUNITY_READY":
                item = self.map_evidence(ident)
            elif ws.state == "EVIDENCE_READY":
                assessment = latest(self.db, self.user, ident, "OpportunityAssessment", required=False)
                if assessment is None or assessment.status not in {"ACTIVE", "LOCKED"}:
                    from career.assessment import assess

                    item = assess(self, ident)
                else:
                    item = self.strategy(ident)
            elif ws.state == "WAITING_STRATEGY_APPROVAL":
                raise ValueError("전략을 읽고 “이걸로 가자”로 승인해 주세요.")
            elif qid and (
                (current_brief := latest(self.db, self.user, ident, "QuestionBrief", qid, required=False)) is not None
                and current_brief.status == "ACTIVE"
            ):
                from career.claim_test import require_pass

                proof = latest(self.db, self.user, ident, "ClaimEvidenceTest", qid, required=False)
                if proof is None or proof.status not in {"ACTIVE", "LOCKED"} or proof.data.get("brief_id") != current_brief.id:
                    item = self.test_claim(ident, qid)
                else:
                    require_pass(self, ident, qid, current_brief)
                    raise ValueError("근거 검증을 통과했습니다. 문항 메시지를 읽고 승인해 주세요.")
            elif len(ws.data.get("questions", [])) > 1 and (
                (portfolio := latest(self.db, self.user, ident, "QuestionPortfolio", required=False)) is None
                or portfolio.status != "LOCKED"
            ):
                if portfolio and portfolio.status == "ACTIVE":
                    raise ValueError("문항별 역할과 메시지 후보를 먼저 승인해 주세요.")
                from career.portfolio import plan

                item = plan(self, ident)
            elif qid:
                brief = latest(self.db, self.user, ident, "QuestionBrief", qid, required=False)
                if brief is None or brief.status not in {"ACTIVE", "LOCKED"}:
                    item = self.question_brief(ident, qid)
                elif brief.status == "ACTIVE":
                    raise ValueError("문항 메시지를 먼저 승인해 주세요.")
                elif (
                    brief.status == "LOCKED"
                    and ((prior_draft := latest(self.db, self.user, ident, "Draft", qid, required=False)) is None
                         or prior_draft.status not in {"ACTIVE", "LOCKED"})
                ):
                    item = self.draft(ident, qid)
                else:
                    document = self.artifact(ident, "Draft", qid)
                    current_review = latest(self.db, self.user, ident, "Review", qid, required=False)
                    if document.status == "LOCKED":
                        return self.prepare_after_lock(ident)
                    if current_review is None or current_review.status not in {"ACTIVE", "LOCKED"}:
                        item = self.review(ident, qid)
                    elif any(i["priority"] in {"P0", "P1"} for i in current_review.data["issues"]):
                        raise ValueError("검수 문제를 먼저 수정해 주세요.")
                    else:
                        item = self.final_lock(ident, qid)
            else:
                raise ValueError("다음 작업 또는 문항을 선택해 주세요. 동결·제출은 별도 확인이 필요합니다.")
            patched = [item.id]
        elif action == "이걸로 가자":
            item = self.approve_question(ident, qid) if qid else self.approve_strategy(ident)
            patched = [item.id]
        elif action == "잠가":
            if resume:
                item = self.final_lock(ident, resume=True)
            elif ws.state == "READY_TO_FREEZE":
                item = self.freeze(ident)
            elif not qid and ws.state == "WAITING_STRATEGY_APPROVAL":
                item = self.approve_strategy(ident)
            elif qid and self.artifact(ident, "QuestionBrief", qid).status == "ACTIVE":
                item = self.approve_question(ident, qid)
            else:
                item = self.final_lock(ident, qid)
            patched = [item.id]
        elif action == "다시":
            if resume:
                item = self.resume(ident)
            elif qid:
                old = latest(self.db, self.user, ident, "Draft", qid, required=False)
                item = self.draft(ident, qid) if old else self.question_brief(ident, qid)
            elif ws.state == "OPPORTUNITY_READY":
                item = self.analyze(ident)
            elif ws.state == "EVIDENCE_READY":
                item = self.map_evidence(ident)
            elif ws.state in {"WAITING_STRATEGY_APPROVAL", "STRATEGY_LOCKED"}:
                item = self.strategy(ident)
            else:
                raise ValueError("재생성할 단계나 문항을 선택해 주세요.")
            patched = [item.id]
        elif action in {"이건 Adjacent", "RAG 빼"}:
            self.editable(ws)
            if action == "RAG 빼" and qid:
                brief = self.artifact(ident, "QuestionBrief", qid)
                data = deepcopy(brief.data)
                data["evidence_ids"] = [
                    i
                    for i in data["evidence_ids"]
                    if "rag"
                    not in (
                        owned(self.db, Evidence, self.user, i).title
                        + " "
                        + owned(self.db, Evidence, self.user, i).body
                    ).lower()
                ]
                item, changed = save(
                    self.db, self.user, ident, "QuestionBrief", data, deps=brief.depends_on, slot=qid
                )
                if not data["evidence_ids"]:
                    item.status = "INVALID"
                    self.question_state(ident, qid, "STALE")
                    ws.state = "NEED_USER_ACTION"
            else:
                pack = self.artifact(ident, "EvidencePack")
                data = deepcopy(pack.data)
                found = False
                for entry in data["items"]:
                    e = owned(self.db, Evidence, self.user, entry["evidence_id"])
                    if (action == "이건 Adjacent" and e.id == evidence_id) or (
                        action == "RAG 빼" and "rag" in (e.title + " " + e.body).lower()
                    ):
                        entry["classification"] = "ADJACENT" if action == "이건 Adjacent" else "NO_EVIDENCE"
                        found = True
                if not found:
                    raise ValueError("수정할 근거를 선택해 주세요.")
                opportunity = self.artifact(ident, "OpportunityBrief")
                covered = {e["job_output_id"] for e in data["items"] if e["classification"] != "NO_EVIDENCE"}
                data["uncovered_outputs"] = [
                    o for o in opportunity.data["actual_outputs"] if o not in covered
                ]
                item, changed = save(
                    self.db,
                    self.user,
                    ident,
                    "EvidencePack",
                    data,
                    deps=pack.depends_on,
                    sources=pack.source_ids,
                )
                ws.state = "EVIDENCE_READY"
            patched = [item.id]
        elif action in {"이건 내가 한 거 아님", "이 수치 틀림"}:
            e = owned(self.db, Evidence, self.user, evidence_id)
            old = view(e)
            e.status = "CONFLICTED"
            if action == "이건 내가 한 거 아님":
                previous_ownership = e.data.get("ownership")
                e.data = {**e.data, "ownership": {
                    **(previous_ownership if isinstance(previous_ownership, dict) else {}),
                    "implementation": "UNKNOWN"}}
            changed = stale(self.db, self.user, [e.source_id])
            from career.projections import CorrectionRecord

            self.db.add(
                CorrectionRecord(
                    user_id=self.user,
                    source_id=e.source_id,
                    evidence_id=e.id,
                    key=action,
                    data={"evidence_id": e.id, "command": action},
                )
            )
            self.db.add(
                Record(
                    user_id=self.user,
                    kind="Correction",
                    data={
                        "evidence_id": e.id,
                        "before": {**old, "created_at": old["created_at"].isoformat()},
                        "command": action,
                    },
                )
            )
            patched = [e.id]
        else:
            raise ValueError(
                "지원하는 명령: ㄱㄱ, 이걸로 가자, 잠가, 다시, 이건 Adjacent, RAG 빼, 이건 내가 한 거 아님, 이 수치 틀림, 제출했다"
            )
        return {
            "interpreted_action": action,
            "patched_artifacts": patched,
            "stale_artifacts": changed,
            "message": "저장된 상태에 반영했습니다.",
        }
