"use client";
import {
  FormEvent,
  ReactNode,
  createContext,
  useContext,
  useCallback,
  useEffect,
  useRef,
  useMemo,
  useState,
} from "react";
import { ConversationWorkspace } from "./conversation-workspace";
import { createApiClient } from "./api-client";
import { resumeBudget, resumeBudgetLabel } from "./resume-budget";
import { EditorDialog, type EditorHandle } from "./editor-dialog";
import { UsageSettings } from "./usage-settings";
import { SourceUpload, ResumeFiles } from "./document-tools";
import { ProvenancePanel } from "./provenance-panel";
import { KnowledgeSearch, SemanticMapping } from "./knowledge-search";
import { CorrectionInbox, RuleControls } from "./correction-controls";
import { ProviderSettings } from "./provider-settings";
import { AdminConsole } from "./admin-console";
import { PublicEntry, Onboarding, PublicFooter } from "./public-entry";
import { AccountSettings } from "./account-settings";
import { GuestSessionNotice } from "./guest-session-notice";
import { downloadPrivateExport } from "./private-export";
import { loadPublicService, type PublicService } from "./public-service";
import { ExperienceOptions } from "./experience-options";
import { ClaimEvidencePanel } from "./claim-evidence-test";
import { ReviewResponsePanel, responsesComplete } from "./review-responses";
import { ResearchStatus } from "./research-status";
import { ResearchPanel } from "./research-panel";
import { ExpressionLibrary } from "./expression-library";
import { FinalReview } from "./final-review";
import { ProjectBoundary } from "./project-boundary";
import {
  accessToken,
  clearSession,
  configureAuth,
  hasSession,
  signIn,
  signOut,
  type AuthConfiguration,
} from "./auth-client";
import {
  AssessmentEditor,
  FactConflictReview,
  OpportunityRankings,
  ReferenceSettings,
  RevisionInbox,
} from "./review-controls";

type Json = string | number | boolean | null | Json[] | { [key: string]: Json };
type Data = { [key: string]: Json };
export type Artifact = {
  id: string;
  kind: string;
  slot: string;
  version: number;
  status: string;
  data: Data;
};
type Question = { id: string; text: string; limit: number };
export type Workspace = {
  id: string;
  company: string;
  role: string;
  jd_raw: string;
  state: string;
  data: {
    questions: Question[];
    submitted_at?: string;
    closed_at?: string;
    closure_reason?: string;
  };
  artifacts: Artifact[];
};
type Evidence = {
  id: string;
  title: string;
  body: string;
  status: string;
  kind: string;
  source_id: string;
};
const stages = [
  "직무·근거",
  "지원 전략",
  "문항 작성",
  "이력서",
  "검수·제출",
  "면접·결과",
];
const stateLabels: Record<string, string> = {
  CREATED: "공고 등록",
  OPPORTUNITY_READY: "직무 분석 완료",
  EVIDENCE_READY: "근거 연결 완료",
  WAITING_STRATEGY_APPROVAL: "전략 승인 대기",
  STRATEGY_LOCKED: "전략 승인 완료",
  COMPOSING: "문항 설계·작성",
  REVIEWING: "검수 중",
  READY_TO_FREEZE: "보관 준비 완료",
  SUBMISSION_FROZEN: "최종본 보관 · 미제출",
  SUBMITTED: "제출 확인 완료",
  CLOSED: "추적 종료 · 기록 보관",
  NEED_USER_ACTION: "근거 변경 · 재검토 필요",
};
const kindLabels: Record<string, string> = {
  OpportunityBrief: "직무 분석",
  OpportunityAssessment: "지원 가치·우선순위",
  EvidencePack: "직무별 근거",
  ApplicationBrief: "지원 전략",
  QuestionBrief: "문항 메시지",
  ClaimEvidenceTest: "메시지 근거 검증",
  QuestionPortfolio: "문항별 역할",
  Draft: "자기소개서",
  ResumeBrief: "이력서 구성",
  ResumeContent: "이력서",
  Review: "문항 검수",
  ResumeReview: "이력서 검수",
  ReviewResponses: "문항 검수 답변",
  ResumeReviewResponses: "이력서 검수 답변",
  ExperienceSelection: "선택한 경험",
  PortfolioReview: "전체 문서 검수",
  SubmissionBundle: "제출 보관본",
  InterviewHandoff: "면접 준비",
  Postmortem: "결과 회고",
  CompanyResearchResult: "회사 조사",
  ResearchReview: "채용 배경 확인",
  ApprovedExpression: "승인한 표현",
  FinalSubmissionReview: "직업 정체성·마지막 세 질문",
};
const fieldLabels: Record<string, string> = {
  final_questions: "제출 당시 확인한 마지막 세 질문",
  role_noun: "문서에서 드러나는 직업 명칭",
  assignment_answer: "맡길 수 있는 업무",
  motivation_answer: "본업을 하고 싶은 이유",
  evidence_answer: "경험이 업무 역량의 근거가 되는 이유",
  gaps_answer: "남아 있는 공백과 한계",
  return_stage: "돌아가서 보완할 단계",
  expression_usage: "이번 작성에 참고한 승인 표현",
  original_excerpt_rechecked: "원문을 현재 근거로 재대조함",
  source_documents: "조사 원문",
  extraction_status: "자료 정리 상태",
  why_now_proposals: "채용 배경 가설 후보",
  research_id: "조사 버전",
  limitation: "미확인 정보와 한계",
  scope_reviewed: "조사 범위 확인",
  why_now_confirmed: "채용 배경 가설 확인",
  reviewed_at: "확인 일시",
  scope: "조사 범위",
  research_complete: "전체 조사 완료",
  review_responses: "제출 당시 확인한 검수 답변",
  response_tasks: "답변·처리가 필요한 질문",
  entries: "질문별 답변",
  answer: "내 답변",
  verification_rationale: "답변 확인 결과",
  category: "확인할 내용",
  task: "검수 질문",
  unanswered_task_ids: "아직 답하지 않은 질문",
  fact_authority: "사실 자료로 사용 가능 여부",
  implementation_status: "진행·검증 범위",
  measurement_context: "측정 환경",
  measured_at: "측정 시점",
  business_effect: "실제 업무 성과를 측정한 지표",
  output_importance: "업무 중요도",
  output: "업무 산출물",
  importance: "중요도",
  required: "필수 조건",
  preferred: "우대 조건",
  requirement: "지원 조건",
  posting_status: "채용 상태",
  posting_source: "채용 확인 출처",
  verified_at: "현재 상태 확인일",
  deadline_at: "마감 시각",
  deadline_timezone: "마감 시간대",
  eligibility: "지원 자격",
  profile_keys: "프로필 근거",
  fit: "직무 적합도",
  career_value: "커리어 가치",
  action_priority: "지금 행동 순서",
  level: "판단 수준",
  reason: "판단 근거",
  preparation_cost: "준비 비용",
  recommendation: "지원 추천",
  main_fix: "우선 보완할 점",
  critical_gaps: "핵심 업무의 근거 공백",
  human_decision: "내 결정",
  operational_value: "가능하게 한 업무·운영 가치",
  value_scope: "성과 표현 범위",
  expression_angle: "표현 관점",
  sections: "이력서 섹션",
  bullets: "작성 항목",
  quote: "원자료 인용",
  missing_information: "추가로 확인할 내용",
  items: "정리 항목",
  identity_role: "이 문항에서 보여줄 역할",
  primary_message_candidates: "핵심 메시지 후보",
  evidence_candidate_ids: "연결할 경험 후보",
  avoided_repetition: "피할 반복",
  section_order: "섹션 순서",
  section_budget: "섹션별 분량",
  max_characters: "최대 글자 수",
  max_bullets: "최대 항목 수",
  evidence_ranking: "근거 우선순위",
  rank: "순위",
  skill_focus: "역량 구분",
  skill_name: "연결한 역량",
  concrete_output: "확인한 산출물",
  understandable_hook: "경험을 설명할 단서",
  recency_date: "근거 확인일",
  historical_jd_signals: "과거 공고의 직무 신호",
  date_label: "당시 공고 날짜",
  historical_only: "과거 신호로만 사용",
  official_facts: "출처를 확인한 회사 사실",
  external_evidence: "외부 자료",
  statement: "내용",
  hypotheses: "추가 확인할 회고 가설",
  hypothesis_mode: "회고 작성 방식",
  confidence: "확신 수준",
  attribution_scope: "검토할 전형 단계",
  validation_needed: "추가 확인 방법",
  origin: "작성 근거",
  reconstruction_mode: "당시 자료 재구성 기준",
  reconstruction_warning: "재구성 한계",
  user_notes: "내가 남긴 전형 메모",
  notes_authority: "메모의 확인 범위",
  known_reason: "확인된 원인",
  reverse_mapping: "당시 주장과 근거 대조",
  job_outputs: "업무와 연결한 경험",
  output_relations: "연결한 업무",
  known_gaps: "당시 확인한 공백",
  document_id: "문서",
  document_version: "문서 버전",
  historical_jd: "당시 공고 원문",
  claim: "당시 주장",
  uncovered: "근거 공백 여부",
  evidence: "당시 사용한 경험",
  kind: "항목 유형",
  name: "이름",
  value: "값",
  unit: "단위",
  dataset: "데이터 범위",
  subset: "부분집합",
  experiment_version: "실험 버전",
  baseline: "비교 기준",
  denominator: "모수",
  valid_for_claims: "사용 가능한 주장",
  invalid_for_claims: "사용할 수 없는 주장",
  situation: "상황",
  constraint: "제약",
  observation: "관찰",
  options: "비교한 선택지",
  action: "행동·처리",
  outcome: "결과",
  lesson: "배운 점",
  summary: "요약",
  hypothesis: "가설",
  experiment: "실험",
  problem_definition: "문제 정의",
  experiment_design: "실험 설계",
  integration: "통합",
  result_scope: "성과 범위",
  safe_claim: "사용 가능한 표현",
  forbidden_claim: "사용 금지 표현",
  rationale: "이유",
  specialty: "전문 분야",
  tools: "사용 도구",
  differentiators: "차별 역량",
  hiring_context: "채용 배경",
  selection_process_signals: "전형 정보",
  retrieved_at: "확인 시각",
  published_at: "게시 시각",
  freshness: "정보 시점",
  source_type: "출처 유형",
  source_id: "출처",
  evidence_id: "근거",
  job_output_id: "업무 산출물",
  evidence_strength: "근거 강도",
  ownership_strength: "수행 범위 확실성",
  ownership: "수행 범위",
  implementation: "구현",
  verification_status: "검증 상태",
  claim_boundaries: "주장 한계",
  forbidden_claims: "사용 금지 주장",
  top_capabilities: "주요 역량",
  project_order: "프로젝트 순서",
  page_budget: "페이지 목표",
  bullet_intents: "항목 구성",
  selected_evidence_ids: "사용 근거",
  target_role: "목표 직무",
  fatal_gap_strategy: "부족한 근거 대응",
  main_skill_message: "핵심 역량 메시지",
  differentiator_message: "차별점 메시지",
  base_profession_identity: "본업 정체성",
  question_portfolio: "문항 역할",
  do_not_position_as: "피해야 할 포지셔닝",
  decision: "핵심 판단",
  insight: "배운 점",
  job_relevance: "직무 연결",
  question_type: "문항 유형",
  question_id: "문항",
  supporting_claims: "뒷받침 주장",
  actual_outputs: "실제 업무 산출물",
  base_profession: "본업",
  main_skills: "핵심 역량",
  positioning: "포지셔닝",
  assignment_statement: "입사 후 맡길 수 있는 일",
  fatal_gaps: "현재 부족한 근거",
  selection_risks: "전형 리스크",
  primary_message: "핵심 메시지",
  evaluation_intent: "질문 의도",
  evidence_ids: "선택 근거",
  company_source_ids: "회사 사실 출처",
  company_defense_sources: "제출 당시 회사 사실 출처",
  freshness_at_submission: "제출 당시 정보 시점",
  text: "본문",
  issues: "검수 의견",
  message: "의견",
  followups: "예상 질문",
  company_facts: "회사 사실",
  company_inferences: "회사 추론",
  uncovered_outputs: "근거가 없는 업무",
  classification: "관계",
  status: "상태",
  mode: "확인 방법",
  sources: "조사 출처",
  role_signals: "직무 신호",
  claims: "주장과 근거",
  support: "근거 확인",
  ownership_ok: "수행 범위 확인",
  claim_defense: "주장 방어",
  defense_evidence: "주장을 뒷받침한 경험",
  defense_status: "방어 자료 확인",
  source_quote: "제출 당시 근거 원문",
  raw_source_quote: "원자료에 기록한 내용",
  why_this_decision: "선택한 판단",
  alternatives: "검토한 대안",
  turning_point: "방향을 바꾼 관찰",
  limitations: "주장 범위와 한계",
  metric_scope: "수치와 측정 범위",
  metric_id: "지표",
  metrics: "확인한 지표",
  target_seconds: "설명 연습 목표 (초)",
  timing_status: "설명 시간 확인",
  gap: "확인된 공백",
  acknowledgement: "솔직하게 인정할 범위",
  frozen_strategy_quote: "제출 당시 보완 전략",
  safe_answer: "답변 시 지킬 범위",
  job_context: "제출 당시 회사·직무",
  basis: "자료 기준",
  ownership_notes: "수행 범위",
  metric_scope_notes: "수치 범위",
  expected_followups: "예상 꼬리질문",
  fatal_gap_answers: "부족한 근거",
  project_explanations: "프로젝트 설명 재료",
  one_minute: "1분",
  three_minute: "3분",
  five_minute: "5분",
  writing_rule_updated: "작성 규칙 변경 여부",
};
function lines(v: string) {
  return v
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
}
function Field({
  name,
  label,
  area = false,
  value = "",
  type = "text",
}: {
  name: string;
  label: string;
  area?: boolean;
  value?: string;
  type?: string;
}) {
  return (
    <label>
      {label}
      {area ? (
        <textarea name={name} defaultValue={value} />
      ) : (
        <input name={name} type={type} defaultValue={value} />
      )}
    </label>
  );
}
const ReferenceNames = createContext<Record<string, string>>({});
const valueLabels: Record<string, string> = {
  DETERMINISTIC: "현재 근거로 규칙 검사",
  AI_AND_DETERMINISTIC: "근거 검사와 AI 대조",
  PASSED: "충돌 없음",
  WARNINGS: "확인할 권고 있음",
  NEEDS_REVISION: "수정 필요",
  JD_ONLY: "등록한 공고 기준",
  SOURCE_BACKED_PARTIAL: "등록한 출처 범위",
  HYPOTHESIS: "공개 근거에 따른 가설",
  INSUFFICIENT: "자료 부족을 확인하고 진행",
  NEEDS_EXTRACTION: "원문 정보 정리 필요",
  EXTRACTED: "원문 인용과 함께 정리됨",
  COLLECTED_PUBLIC_SOURCES: "공개 자료 원문 수집",
  QUOTED_SOURCE_RESEARCH: "인용에 근거한 조사 정리",
  RESOLVED: "처리 완료",
  NEEDS_ACTION: "보완 필요",
  MIXED_REVIEW: "직접 대조와 AI 검토",
  ANSWER_WITH_EVIDENCE: "현재 근거로 답변",
  REVISE_DOCUMENT: "문서에서 보완",
  ADD_EVIDENCE: "근거 보완 후 재검수",
  INTERVIEW_PREP: "면접 답변 준비",
  ACKNOWLEDGE_GAP: "공백 인정과 대응",
  GROUNDING: "사실 확인",
  JOB_MOTIVATION: "본업·지원 의향",
  INTERVIEW_PREPARATION: "면접 설명",
  RECRUITER_RISK: "채용 관점의 위험",
  IMPLEMENTED: "구현함",
  EXPERIMENT_VERIFIED: "실험으로 검증함",
  PARTIAL_EXPLORATORY: "부분 구현·탐색",
  DESIGN_IDEA: "설계·아이디어",
  NOT_DONE: "수행하지 않음",
  EXPERIMENT: "실험",
  PROTOTYPE: "프로토타입",
  PRODUCTION: "실제 운영",
  OPEN: "채용 중",
  CLOSED: "마감",
  UNCERTAIN: "현재 상태 확인 필요",
  CRITICAL: "필수 핵심 업무",
  CORE: "주요 업무",
  SUPPORTING: "보조 업무",
  MET: "자격 충족",
  NOT_MET: "자격 미충족",
  NEEDS_VERIFICATION: "확인 필요",
  HIGH: "높음",
  MEDIUM: "보통",
  LOW: "낮음",
  NOW: "현재 근거로 지원 가능",
  SHORT: "1~3일 보완",
  PROCEED: "지원 추천",
  PROCEED_WITH_GAP: "공백을 인정하고 지원",
  LOW_PRIORITY: "우선순위 낮음",
  SKIP: "건너뛰기 추천",
  PENDING: "검토 대기",
  TECHNICAL_RESULT: "검증한 기술 결과",
  OPERATIONAL_POSSIBILITY: "운영 적용 가능성",
  MEASURED_BUSINESS_IMPACT: "측정한 업무 성과",
  Project: "프로젝트",
  DecisionEpisode: "판단 경험",
  Metric: "성과 지표",
  Ownership: "수행 범위",
  ClaimBoundary: "주장 한계",
  USER: "직접 수행",
  USER_AI_ASSISTED: "AI 도움을 받아 수행",
  USER_MODIFIED_EXISTING_CODE: "기존 코드 수정",
  TEAM: "팀 수행",
  LAB: "연구실 수행",
  UNKNOWN: "확인 필요",
  UNVERIFIED: "확인 전",
  USER_CONFIRMED: "직접 확인",
  VERIFIED: "검증 완료",
  SOURCE_BACKED: "출처 확인",
  CONFLICTED: "충돌 · 정정 필요",
  DO_NOT_USE: "사용 중지",
  CANDIDATE: "검토할 후보",
  CANONICAL: "승인된 기준",
  DIRECT: "직접 근거",
  ADJACENT: "인접 근거",
  NO_EVIDENCE: "근거 없음",
  STRONG: "강함",
  MODERATE: "보통",
  LIMITED: "제한적",
  SUPPORTED: "근거 확인",
  NEEDS_REVIEW: "재검토 필요",
  MANUAL_JD_ONLY: "입력한 공고 기준",
  USER_VERIFIED: "직접 검토",
  AI_REVIEWED: "AI 검토",
  MAIN_SKILL: "핵심 역량",
  DIFFERENTIATOR: "차별 역량",
  UNSPECIFIED: "역량 연결 확인 필요",
  SUMMARY: "소개",
  PROJECT: "프로젝트",
  EXPERIENCE: "경력",
  EDUCATION: "학력",
  SKILLS: "역량",
  DATED: "과거 시점 자료",
  CURRENT: "현재 시점 자료",
  DOCUMENT: "서류",
  CODING: "코딩 테스트",
  INTERVIEW: "면접",
  FINAL: "최종 전형",
  RECORDED_OBSERVATIONS: "저장된 기록 대조",
  MODEL_DRAFT_WITH_RECORDED_OBSERVATIONS: "기록 대조와 AI 가설",
  MODEL_HYPOTHESIS_NOT_VERIFIED_CAUSE: "확인되지 않은 AI 가설",
  USER_REPORTED_NOT_VERIFIED_CAUSE: "사용자 메모 · 원인으로 확인되지 않음",
  EXACT_FROZEN_SUBMISSION: "불변 제출 보관본",
  CURRENT_RECORDS_SUBMISSION_NOT_RECONSTRUCTABLE:
    "현재 기록 · 실제 제출본 미확인",
};
const ReviewFeedback = createContext<
  ((id: string, index: number, valid: boolean) => Promise<unknown>) | null
>(null);
function DataView({ data }: { data: Json }) {
  const names = useContext(ReferenceNames);
  if (data === null) return <span className="muted">미등록</span>;
  if (typeof data === "boolean") return <span>{data ? "예" : "아니요"}</span>;
  if (typeof data !== "object")
    return typeof data === "string" && /^https?:\/\//.test(data) ? (
      <a href={data} target="_blank" rel="noreferrer">
        {data}
      </a>
    ) : (
      <span>
        {names[String(data)] || valueLabels[String(data)] || String(data)}
      </span>
    );
  if (Array.isArray(data))
    return data.length ? (
      <ul>
        {data.map((v, i) => (
          <li key={i}>
            <DataView data={v} />
          </li>
        ))}
      </ul>
    ) : (
      <span className="muted">없음</span>
    );
  return (
    <dl>
      {Object.entries(data)
        .filter(
          ([, v]) => v !== null && v !== "" && !(Array.isArray(v) && !v.length),
        )
        .filter(
          ([k]) =>
            ![
              "source_ids",
              "depends_on",
              "prompt_version",
              "model_version",
              "artifact_id",
              "workspace_id",
              "supporting_outcome_id",
              "supporting_artifact_ids",
              "candidate_rule_ids",
              "submission_bundle_id",
              "retrieval_metadata",
              "source_documents",
              "extraction_citations",
              "research_id",
              "context_hash",
              "repetition_policy",
            ].includes(k),
        )
        .map(([k, v]) => (
          <div key={k}>
            <dt>{fieldLabels[k] || k}</dt>
            <dd>
              <DataView data={v} />
            </dd>
          </div>
        ))}
    </dl>
  );
}
function Panel({
  title,
  children,
  open = false,
}: {
  title: string;
  children: ReactNode;
  open?: boolean;
}) {
  return (
    <details className="panel" open={open}>
      <summary>
        {title}
        <span className="expand-hint">펼치기 / 접기</span>
      </summary>
      <div className="panel-body">{children}</div>
    </details>
  );
}
function ExperienceStructure({
  evidence,
  request,
  ai,
  refresh,
}: {
  evidence: Evidence;
  request: (
    path: string,
    body?: unknown,
  ) => Promise<{ id: string; data: Data }>;
  ai: boolean;
  refresh: () => Promise<void>;
}) {
  const [proposal, setProposal] = useState<{ id: string; data: Data } | null>(
      null,
    ),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [selectedItems, setSelectedItems] = useState<number[]>([]),
    [editedItems, setEditedItems] = useState<Data[]>([]),
    [confirmed, setConfirmed] = useState(false);
  const extract = async (manual = false) => {
    setBusy(true);
    setError("");
    try {
      const result = await request(
        `/evidence/${evidence.id}/extract`,
        manual
          ? {
              manual: {
                items: [
                  {
                    kind: "Project",
                    quote: evidence.body,
                    payload_json: JSON.stringify({
                      name: evidence.title,
                      summary: evidence.body,
                    }),
                  },
                  {
                    kind: "Ownership",
                    quote: evidence.body,
                    payload_json: JSON.stringify({ implementation: "UNKNOWN" }),
                  },
                ],
                missing_information: [
                  "직접 수행·AI 보조·팀 수행 범위",
                  "수치의 표본·기준·측정 환경",
                  "구현·실험·실제 배포 범위",
                ],
              },
            }
          : {},
      );
      setProposal(result);
      const items = result.data.items as Data[];
      setSelectedItems(items.map((_, i) => i));
      setEditedItems(items.map((item) => item.data as Data));
      setConfirmed(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "경험을 정리하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  };
  const apply = async () => {
    if (!proposal) return;
    setBusy(true);
    setError("");
    try {
      await request(`/extractions/${proposal.id}/apply`, {
        confirmed,
        selections: selectedItems.map((index) => ({
          index,
          data: editedItems[index],
        })),
      });
      setProposal({ ...proposal, data: { ...proposal.data, applied: true } });
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "저장하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="experience-structure">
      <button
        className="secondary"
        disabled={busy || !ai}
        onClick={() => void extract()}
      >
        {busy ? "경험을 정리하고 있어요…" : "경험 · 판단 · 성과 구조화"}
      </button>
      <button
        className="secondary"
        disabled={busy}
        onClick={() => void extract(true)}
      >
        원자료 보며 직접 구조화
      </button>
      {!ai && (
        <p className="muted">
          AI를 연결하면 원자료에서 확인할 항목을 추출할 수 있습니다.
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {proposal && (
        <div className="extraction-proposal">
          <h3>확인할 경험 항목</h3>
          {(proposal.data.items as Data[]).map((item, index) => (
            <div className="extraction-item" key={index}>
              <label className="check">
                <input
                  type="checkbox"
                  checked={selectedItems.includes(index)}
                  disabled={
                    Boolean(proposal.data.applied) ||
                    proposal.data.status === "REJECTED"
                  }
                  onChange={(e) => {
                    setSelectedItems(
                      e.target.checked
                        ? [...selectedItems, index]
                        : selectedItems.filter((i) => i !== index),
                    );
                    setConfirmed(false);
                  }}
                />
                {valueLabels[String(item.kind)] || String(item.kind)} 반영
              </label>
              <blockquote>{String(item.quote)}</blockquote>
              <details>
                <summary>항목 확인·수정</summary>
                {Object.entries(editedItems[index] || {})
                  .filter(
                    ([key]) =>
                      !["source_id", "evidence_id", "status"].includes(key),
                  )
                  .map(([key, value]) => {
                    const change = (text: string) => {
                      const next = [...editedItems];
                      next[index] = {
                        ...next[index],
                        [key]: Array.isArray(value)
                          ? lines(text)
                          : value === null && !text
                            ? null
                            : text,
                      };
                      setEditedItems(next);
                      setConfirmed(false);
                    };
                    const ownershipFields = [
                      "problem_definition",
                      "hypothesis",
                      "experiment_design",
                      "implementation",
                      "integration",
                      "result_scope",
                    ];
                    return (
                      <label key={key}>
                        {fieldLabels[key] || key}
                        {typeof value === "boolean" ? (
                          <input
                            type="checkbox"
                            checked={value}
                            onChange={(e) => {
                              const next = [...editedItems];
                              next[index] = {
                                ...next[index],
                                [key]: e.target.checked,
                              };
                              setEditedItems(next);
                              setConfirmed(false);
                            }}
                          />
                        ) : [
                            "implementation_status",
                            "measurement_context",
                          ].includes(key) ? (
                          <select
                            value={String(value)}
                            onChange={(e) => change(e.target.value)}
                          >
                            {(key === "implementation_status"
                              ? [
                                  "UNKNOWN",
                                  "IMPLEMENTED",
                                  "EXPERIMENT_VERIFIED",
                                  "PARTIAL_EXPLORATORY",
                                  "DESIGN_IDEA",
                                  "NOT_DONE",
                                ]
                              : [
                                  "UNKNOWN",
                                  "EXPERIMENT",
                                  "PROTOTYPE",
                                  "PRODUCTION",
                                ]
                            ).map((option) => (
                              <option key={option} value={option}>
                                {valueLabels[option]}
                              </option>
                            ))}
                          </select>
                        ) : item.kind === "Ownership" &&
                          ownershipFields.includes(key) ? (
                          <select
                            value={String(value)}
                            onChange={(e) => change(e.target.value)}
                          >
                            {[
                              "UNKNOWN",
                              "USER",
                              "USER_AI_ASSISTED",
                              "USER_MODIFIED_EXISTING_CODE",
                              "TEAM",
                              "LAB",
                            ].map((option) => (
                              <option key={option} value={option}>
                                {valueLabels[option]}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <textarea
                            value={
                              Array.isArray(value)
                                ? value.join("\n")
                                : String(value ?? "")
                            }
                            onChange={(e) => change(e.target.value)}
                          />
                        )}
                      </label>
                    );
                  })}
              </details>
            </div>
          ))}
          <DataView data={proposal.data.missing_information} />
          {proposal.data.applied || proposal.data.status === "REJECTED" ? (
            <p className="note">
              {proposal.data.applied
                ? "선택한 항목을 경험 저장소에 반영했습니다."
                : "제안을 거절했습니다. 원자료는 유지됩니다."}
            </p>
          ) : (
            <>
              <label className="check">
                <input
                  type="checkbox"
                  checked={confirmed}
                  onChange={(e) => setConfirmed(e.target.checked)}
                />
                원자료와 대조해 추출된 내용·지표 범위·수행 범위를 확인했습니다.
              </label>
              <button
                disabled={
                  busy ||
                  !confirmed ||
                  !selectedItems.length ||
                  !["USER_CONFIRMED", "SOURCE_BACKED", "VERIFIED"].includes(
                    evidence.status,
                  )
                }
                onClick={() => void apply()}
              >
                확인한 항목 저장
              </button>
              <button
                className="secondary"
                disabled={busy}
                onClick={() =>
                  void request(`/extractions/${proposal.id}/apply`, {
                    decision: "REJECT",
                  })
                    .then(() =>
                      setProposal({
                        ...proposal,
                        data: { ...proposal.data, status: "REJECTED" },
                      }),
                    )
                    .catch((e) => setError(e.message))
                }
              >
                전체 제안 거절
              </button>
              {evidence.status === "UNVERIFIED" && (
                <p className="muted">
                  위의 ‘내용을 직접 확인하고 승인’으로 경험을 먼저 확인해
                  주세요.
                </p>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
function Icon({ name }: { name: string }) {
  const paths: Record<string, ReactNode> = {
    "지원 기회": (
      <>
        <rect x="3" y="6" width="18" height="15" rx="3" />
        <path d="M8 6V3h8v3M3 12h18M10 12v3h4v-3" />
      </>
    ),
    "경험 정리": (
      <>
        <path d="M4 4h6l2 3h8v13H4z" />
        <path d="M8 12h8M8 16h5" />
      </>
    ),
    "검증 기록": (
      <>
        <path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z" />
        <path d="m8 12 3 3 5-6" />
      </>
    ),
    설정: (
      <>
        <path d="M4 7h16M4 17h16" />
        <circle cx="9" cy="7" r="3" />
        <circle cx="15" cy="17" r="3" />
      </>
    ),
    관리자: (
      <>
        <path d="M12 3 3 7v5c0 5 9 9 9 9s9-4 9-9V7z" />
        <path d="M8 12h8M12 8v8" />
      </>
    ),
  };
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name]}
    </svg>
  );
}
function Card({ a }: { a?: Artifact }) {
  const feedback = useContext(ReviewFeedback);
  const [rating, setRating] = useState<Record<number, string>>({});
  const [feedbackError, setFeedbackError] = useState("");
  return a ? (
    <section className="artifact-card">
      <div className="row">
        <h3>
          {kindLabels[a.kind] || a.kind} <small>v{a.version}</small>
        </h3>
        <span className={`badge ${a.status === "STALE" ? "stale" : ""}`}>
          {a.status === "STALE"
            ? "다시 검토 필요"
            : a.status === "LOCKED"
              ? "잠금 완료"
              : a.status === "SUPERSEDED"
                ? "이전 버전"
                : "검토 중"}
        </span>
      </div>
      {a.kind === "EvidencePack" && a.data.retrieval_metadata && (
        <p className="muted">
          경험 탐색 방식 ·{" "}
          {(a.data.retrieval_metadata as Data).semantic_used
            ? "한국어 의미 검색과 키워드"
            : (a.data.retrieval_metadata as Data).semantic_requested
              ? "준비된 의미 검색 자료가 부족해 키워드 사용"
              : "키워드 검색"}
        </p>
      )}
      {a.kind === "PortfolioReview" ? (
        <>
          <p>
            {valueLabels[String(a.data.result)] || "문서 검수 결과"} ·{" "}
            {valueLabels[String(a.data.mode)] || "저장된 검사"}
          </p>
          <p>
            비교한 문서:{" "}
            {((a.data.checked_documents || []) as Data[])
              .map((item) => `${String(item.label)} ${String(item.version)}차`)
              .join(" · ")}
          </p>
          {a.data.complete === false && (
            <p>
              아직 작성하지 않은 문서가 있어 전체 비교는 완료되지 않았습니다.
            </p>
          )}
          {((a.data.issues || []) as Data[]).length ? (
            <ul>
              {(a.data.issues as Data[]).map((issue, index) => (
                <li key={index}>
                  <span className="badge">{String(issue.priority)}</span>{" "}
                  {String(issue.message)}
                </li>
              ))}
            </ul>
          ) : (
            <p>현재 검사에서 문서 간 충돌이나 반복을 발견하지 못했습니다.</p>
          )}
        </>
      ) : a.data.text ? (
        <pre>{String(a.data.text)}</pre>
      ) : (
        <DataView data={a.data} />
      )}
      {feedback &&
        ["Review", "ResumeReview", "PortfolioReview"].includes(a.kind) &&
        Array.isArray(a.data.issues) &&
        a.data.issues.length > 0 && (
          <details>
            <summary>검수 의견 평가하기</summary>
            {(a.data.issues as Data[]).map((issue, index) => (
              <div className="review-feedback" key={index}>
                <p>{String(issue.message)}</p>
                <button
                  className="secondary"
                  onClick={() =>
                    void feedback(a.id, index, true)
                      .then(() =>
                        setRating({ ...rating, [index]: "문제 맞음" }),
                      )
                      .catch(() =>
                        setFeedbackError("평가를 저장하지 못했습니다."),
                      )
                  }
                >
                  문제 맞음
                </button>
                <button
                  className="secondary"
                  onClick={() =>
                    void feedback(a.id, index, false)
                      .then(() =>
                        setRating({ ...rating, [index]: "검수 과함" }),
                      )
                      .catch(() =>
                        setFeedbackError("평가를 저장하지 못했습니다."),
                      )
                  }
                >
                  검수 과함
                </button>
                {rating[index] && (
                  <small role="status">{rating[index]} · 저장됨</small>
                )}
              </div>
            ))}
            {feedbackError && (
              <p className="error" role="alert">
                {feedbackError}
              </p>
            )}
          </details>
        )}
    </section>
  ) : null;
}

export default function Home() {
  const [authConfiguration, setAuthConfiguration] =
    useState<AuthConfiguration | null>(null);
  const [authConfigurationError, setAuthConfigurationError] = useState("");
  const [publicService, setPublicService] = useState<PublicService | null>(
    null,
  );
  const [onboardingVersion, setOnboardingVersion] = useState<string | null>(
    null,
  );
  const [accountOnly, setAccountOnly] = useState(false);
  const [email, setEmail] = useState(""),
    [password, setPassword] = useState("");
  const [token, setToken] = useState(""),
    [authenticated, setAuthenticated] = useState(false),
    [ai, setAi] = useState(false);
  const [screen, setScreen] = useState("지원 기회"),
    [stage, setStage] = useState(stages[0]),
    [list, setList] = useState<Workspace[]>([]),
    [ws, setWs] = useState<Workspace | null>(null),
    [evidence, setEvidence] = useState<Evidence[]>([]);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [qid, setQid] = useState(""),
    [trace, setTrace] = useState<Json | null>(null);
  const api = useMemo(
    () =>
      createApiClient(
        async () => {
          try {
            return authConfiguration?.provider !== "local"
              ? await accessToken()
              : token;
          } catch (error) {
            setAuthenticated(false);
            setOnboardingVersion(null);
            setAccountOnly(false);
            setWs(null);
            setList([]);
            setEvidence([]);
            setTrace(null);
            setQid("");
            throw error;
          }
        },
        () => {
          setAuthenticated(false);
          setOnboardingVersion(null);
          setAccountOnly(false);
          setWs(null);
          setList([]);
          setEvidence([]);
          setTrace(null);
          setQid("");
          if (authConfiguration?.provider === "supabase") clearSession();
        },
      ),
    [token, authConfiguration?.provider],
  );
  const request = api.request;
  const [adminAccess, setAdminAccess] = useState(false);
  useEffect(() => {
    let active = true;
    setAdminAccess(false);
    if (authenticated) {
      request("/admin/access")
        .then((result) => {
          if (active) setAdminAccess(result.is_admin === true);
        })
        .catch(() => {
          if (active) setAdminAccess(false);
        });
    }
    return () => {
      active = false;
    };
  }, [request, authenticated, authConfiguration?.provider]);
  const editorHandle = useRef<EditorHandle>(null);
  const [resumePages, setResumePages] = useState<"1" | "2" | "MASTER">("1");
  const navigate = (action: () => void) =>
    editorHandle.current ? editorHandle.current.beforeLeave(action) : action();
  const navigateScreen = (destination: string) =>
    navigate(() => {
      if (destination === "관리자")
        window.history.pushState(null, "", "#admin");
      else if (window.location.hash === "#admin")
        window.history.pushState(
          null,
          "",
          window.location.pathname + window.location.search,
        );
      setScreen(destination);
      setShowEditor(false);
    });
  useEffect(() => {
    const showAddressedPage = () => {
      const action = () => {
        if (window.location.hash === "#admin") {
          setScreen("관리자");
          setShowEditor(false);
        } else
          setScreen((previous) => (previous === "관리자" ? "설정" : previous));
      };
      if (editorHandle.current) editorHandle.current.beforeLeave(action);
      else action();
    };
    showAddressedPage();
    window.addEventListener("hashchange", showAddressedPage);
    window.addEventListener("popstate", showAddressedPage);
    return () => {
      window.removeEventListener("hashchange", showAddressedPage);
      window.removeEventListener("popstate", showAddressedPage);
    };
  }, []);
  const refresh = useCallback(
    async (id?: string) => {
      setList(await request("/applications"));
      setEvidence(await request("/evidence"));
      if (id) {
        const loaded: Workspace = await request("/applications/" + id);
        setWs(loaded);
        setQid((previous) =>
          loaded.data.questions.some((q) => q.id === previous) ? previous : "",
        );
      }
    },
    [request],
  );
  const refreshAiAvailability = useCallback(async () => {
    const settings = await request("/settings");
    setAi(Boolean(settings.ai_available));
  }, [request]);
  const run = async (fn: () => Promise<unknown>, message = "저장했습니다.") => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await fn();
      setNotice(message);
    } catch (e) {
      setError(e instanceof Error ? e.message : "처리하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  };
  const act = async (action: string, body: object = {}) => {
    if (!ws) return;
    const options = body as { qid?: string; resume?: boolean };
    const kind =
      action === "approve-strategy"
        ? "ApplicationBrief"
        : action === "approve-question"
          ? "QuestionBrief"
          : action === "final-lock"
            ? options.resume
              ? "ResumeContent"
              : "Draft"
            : "";
    await request(`/applications/${ws.id}/actions/${action}`, {
      ...body,
      ...(kind ? { artifact_id: latest(kind, options.qid || "")?.id } : {}),
    });
    await refresh(ws.id);
  };
  const submit =
    (fn: (v: Record<string, string>) => Promise<unknown>) =>
    (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const v = Object.fromEntries(
        new FormData(event.currentTarget).entries(),
      ) as Record<string, string>;
      const saved = editorHandle.current?.beginSave(event.currentTarget);
      void run(async () => {
        await fn(v);
        saved?.();
      });
    };
  const latest = (kind: string, slot = "") =>
    ws?.artifacts
      .filter((a) => a.kind === kind && a.slot === slot)
      .sort((a, b) => b.version - a.version)[0];
  const good = evidence.filter(
    (e) =>
      ["VERIFIED", "SOURCE_BACKED", "USER_CONFIRMED"].includes(e.status) &&
      e.kind !== "EXPRESSION",
  );
  const brief = latest("QuestionBrief", qid),
    draft = latest("Draft", qid),
    resume = latest("ResumeContent");
  const questions = ws?.data.questions || [];
  const experienceReady = [
    latest("OpportunityBrief"),
    latest("EvidencePack"),
  ].every(
    (artifact) => artifact && ["ACTIVE", "LOCKED"].includes(artifact.status),
  );
  const selected = Array.isArray(brief?.data.evidence_ids)
    ? (brief.data.evidence_ids as string[])
    : [];
  useEffect(() => {
    const saved = sessionStorage.getItem("career-token");
    if (saved) setToken(saved);
    let active = true;
    Promise.all([
      fetch("/api/auth/config", {
        cache: "no-store",
        signal: AbortSignal.timeout(15000),
      }),
      loadPublicService(),
    ])
      .then(async ([response, service]) => {
        if (!response.ok) throw new Error("로그인 설정을 불러오지 못했습니다.");
        const config: AuthConfiguration = await response.json();
        if (!active) return;
        configureAuth(config);
        if (config.provider !== "local") {
          sessionStorage.removeItem("career-token");
          setToken("");
        }
        setAuthConfiguration(config);
        setPublicService(service);
      })
      .catch(() => {
        if (active)
          setAuthConfigurationError(
            "로그인 설정을 불러오지 못했습니다. 연결 상태를 확인하고 새로고침해 주세요.",
          );
      });
    return () => {
      active = false;
    };
  }, []);
  const login = (restore = false) =>
    run(async () => {
      setAuthenticated(false);
      setWs(null);
      setList([]);
      setEvidence([]);
      setTrace(null);
      setQid("");
      if (authConfiguration?.provider === "supabase" && !restore) {
        await signIn(email, password);
        setPassword("");
      }
      if (publicService?.access_mode === "public") {
        const account = await request("/account");
        if (account.status === "CLOSED") {
          setAccountOnly(true);
          return;
        }
        setAccountOnly(false);
        const onboarding = await request("/account/onboarding");
        if (onboarding.required) {
          setOnboardingVersion(onboarding.current_version);
          return;
        }
        setOnboardingVersion(null);
      }
      const settings = await request("/settings");
      if (authConfiguration?.provider === "local")
        sessionStorage.setItem("career-token", token);
      setAuthenticated(true);
      setAi(settings.ai_available);
      await refresh();
    }, "연결되었습니다.");
  const manualDocument = (text: string, ids: string[]) => ({
    text,
    claims: lines(text).map((s) => ({
      text: s,
      type: "FACT",
      evidence_ids: ids,
      metric_ids: [],
      support: "SUPPORTED",
      ownership_ok: true,
    })),
  });
  const button = (
    label: string,
    action: string,
    body: object = {},
    disabled = false,
  ) => (
    <button
      type="button"
      disabled={busy || disabled}
      onClick={() => void run(() => act(action, body))}
    >
      {label}
    </button>
  );
  const [showCreate, setShowCreate] = useState(false);
  const [showEditor, setShowEditor] = useState(false);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("전체");
  const disconnect = async () => {
    try {
      if (authConfiguration?.provider === "supabase") await signOut();
    } finally {
      clearSession();
      sessionStorage.removeItem("career-token");
      setToken("");
      setAuthenticated(false);
      setOnboardingVersion(null);
      setAccountOnly(false);
      setWs(null);
      setList([]);
      setEvidence([]);
      setTrace(null);
      setQid("");
    }
  };
  const filtered = list.filter(
    (w) =>
      (w.company + " " + w.role).toLowerCase().includes(query.toLowerCase()) &&
      (filter === "전체" ||
        (filter === "제출 완료"
          ? ["SUBMITTED", "CLOSED"].includes(w.state)
          : !["SUBMITTED", "CLOSED"].includes(w.state))),
  );
  if (!publicService || !authConfiguration)
    return (
      <main className="public-page">
        <section className="onboarding-card">
          <h1>Career Harness</h1>
          <p role={authConfigurationError ? "alert" : "status"}>
            {authConfigurationError || "작업실을 준비하고 있습니다…"}
          </p>
          {authConfigurationError && (
            <button onClick={() => window.location.reload()}>
              다시 불러오기
            </button>
          )}
        </section>
      </main>
    );
  if (publicService.access_mode === "public" && accountOnly)
    return (
      <main className="public-page">
        <section className="onboarding-card">
          <h1>내 계정 관리</h1>
          <AccountSettings
            request={request}
            service={publicService}
            onDeleted={disconnect}
          />
          <div className="public-actions">
            <button className="secondary" onClick={() => void login(true)}>
              작업실로 돌아가기
            </button>
            <button className="secondary" onClick={() => void run(disconnect)}>
              로그아웃
            </button>
          </div>
        </section>
        <PublicFooter service={publicService} />
      </main>
    );
  if (publicService.access_mode === "public" && onboardingVersion)
    return (
      <Onboarding
        service={publicService}
        version={onboardingVersion}
        request={request}
        onAccepted={() => login(true)}
        onCancel={() => void run(disconnect, "로그아웃했습니다.")}
        onAccount={() => setAccountOnly(true)}
      />
    );
  if (publicService.access_mode === "public" && !authenticated)
    return (
      <PublicEntry
        service={publicService}
        onLogin={() => login(true)}
        message={error}
        busy={busy}
      />
    );
  return (
    <ReferenceNames.Provider
      value={Object.fromEntries([
        ...evidence.map((e) => [e.id, e.title]),
        ...evidence.map((e) => [e.source_id, e.title + " 원자료"]),
        ...questions.map((q, i) => [q.id, `${i + 1}번 · ${q.text}`]),
      ])}
    >
      <ReviewFeedback.Provider
        value={(id, index, valid) =>
          request(`/artifacts/${id}/review-labels`, {
            issue_index: index,
            valid,
          })
        }
      >
        <main>
          <aside>
            <a
              className="brand"
              href="#"
              onClick={(e) => {
                e.preventDefault();
                navigate(() => {
                  setScreen("지원 기회");
                  setWs(null);
                  setShowEditor(false);
                });
              }}
            >
              <span className="brand-mark">h</span>
              <span>
                Career Harness<small>나의 커리어 작업실</small>
              </span>
            </a>
            <div className="workspace-person">
              <span className="avatar">나</span>
              <div>
                개인 워크스페이스<small>Private workspace</small>
              </div>
              <span className="live-dot" />
            </div>
            <p className="nav-caption">WORKSPACE</p>
            <div className="aside-nav">
              {[
                "지원 기회",
                "경험 정리",
                "검증 기록",
                "설정",
                ...(adminAccess ? ["관리자"] : []),
              ].map((s) => (
                <button
                  className={screen === s ? "selected" : "nav-button"}
                  key={s}
                  onClick={() => {
                    navigate(() => {
                      setScreen(s);
                      if (s === "관리자")
                        window.history.pushState(null, "", "#admin");
                      else if (window.location.hash === "#admin")
                        window.history.pushState(
                          null,
                          "",
                          window.location.pathname + window.location.search,
                        );
                      if (s === "지원 기회") setWs(null);
                      setShowEditor(false);
                      setNotice("");
                      setError("");
                    });
                  }}
                >
                  <Icon name={s} />
                  <span>{s}</span>
                  {s === "지원 기회" && (
                    <span className="nav-count">{list.length}</span>
                  )}
                </button>
              ))}
            </div>
            <div className="aside-bottom">
              <span className="live-dot" />{" "}
              {authenticated ? "개인 자료 연결됨" : "연결 대기"}
              <p>
                경험은 정확하게.
                <br />
                다음 기회는 선명하게.
              </p>
              <span className="version">Career Harness / 01</span>
            </div>
          </aside>
          <article
            className={
              authenticated && screen === "지원 기회" && ws
                ? "conversation-page"
                : ""
            }
          >
            <div className="topbar">
              <span>
                워크스페이스 <span className="crumb">/</span> {screen}
                {ws && screen === "지원 기회" ? " / " + ws.company : ""}
              </span>
              <span className="connection">
                <span className="live-dot" />
                {ai ? "AI 설정됨" : "직접 작성"}
              </span>
            </div>
            {authenticated && publicService.guest_enabled && (
              <GuestSessionNotice request={request} disabled={busy} />
            )}
            <header className="page-header">
              <div>
                <small className="eyebrow">
                  {screen === "지원 기회"
                    ? "YOUR NEXT CHAPTER"
                    : "YOUR CAREER, GROUNDED"}
                </small>
                <h1>
                  {screen === "지원 기회" && ws
                    ? ws.company
                    : screen === "지원 기회"
                      ? "지원 기회"
                      : screen}
                </h1>
                <p className="subtitle">
                  {screen === "지원 기회" && ws
                    ? ws.role
                    : screen === "지원 기회"
                      ? "경험을 연결하고, 다음 기회를 준비하세요."
                      : screen === "경험 정리"
                        ? "내가 한 일을, 믿을 수 있는 문서의 재료로."
                        : screen === "설정"
                          ? "작업 공간 연결과 개인 자료를 관리하세요."
                          : screen === "관리자"
                            ? "사용량, 연결과 실행 상태를 살펴보세요."
                            : "작성과 검수 과정을 다시 살펴보세요."}
                </p>
              </div>
              {authenticated && screen === "지원 기회" && !ws && (
                <button
                  className="primary"
                  onClick={() => setShowCreate(!showCreate)}
                >
                  {showCreate ? "닫기" : "+ 새 지원 기회"}
                </button>
              )}
            </header>
            {error && (
              <p role="alert" className="error">
                {error}
              </p>
            )}
            {notice && (
              <p role="status" className="note">
                {notice}
              </p>
            )}
            {busy && <p role="status">처리 중입니다…</p>}
            {(!authenticated || screen === "설정") &&
            publicService.access_mode !== "public" ? (
              <section>
                <h3>개인 작업 공간 연결</h3>
                {authConfigurationError && (
                  <p className="error" role="alert">
                    {authConfigurationError}
                  </p>
                )}
                {authConfiguration?.provider === "supabase" ? (
                  <>
                    <p>등록된 계정으로 개인 작업 공간에 로그인하세요.</p>
                    <label>
                      이메일
                      <input
                        type="email"
                        autoComplete="username"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                      />
                    </label>
                    <label>
                      비밀번호
                      <input
                        type="password"
                        autoComplete="current-password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                      />
                    </label>
                  </>
                ) : (
                  <>
                    <p>
                      로컬 실행 시 만든 개인 접속 토큰을 입력하세요. 토큰은 이
                      브라우저 탭에만 저장됩니다.
                    </p>
                    <label>
                      접속 토큰
                      <input
                        type="password"
                        value={token}
                        onChange={(e) => setToken(e.target.value)}
                      />
                    </label>
                  </>
                )}
                <button
                  onClick={() => void login()}
                  disabled={busy || !authConfiguration}
                >
                  {authConfiguration?.provider === "supabase"
                    ? "로그인"
                    : "연결하기"}
                </button>
                {!authenticated &&
                  authConfiguration?.provider === "supabase" &&
                  hasSession() && (
                    <button
                      className="secondary"
                      disabled={busy}
                      onClick={() => void login(true)}
                    >
                      저장된 로그인으로 연결
                    </button>
                  )}
                {authenticated && (
                  <button
                    className="secondary"
                    disabled={busy}
                    onClick={() =>
                      void run(async () => {
                        try {
                          if (authConfiguration?.provider === "supabase")
                            await signOut();
                        } finally {
                          clearSession();
                          sessionStorage.removeItem("career-token");
                          setToken("");
                          setAuthenticated(false);
                          setWs(null);
                          setList([]);
                          setEvidence([]);
                          setTrace(null);
                          setQid("");
                        }
                      }, "로그아웃했습니다.")
                    }
                  >
                    로그아웃
                  </button>
                )}
                <p className="muted">
                  연결 후 설정 화면에서 AI 제공자를 등록할 수 있습니다. 직접
                  작성 모드에서도 근거 연결·승인·검수·보관을 진행할 수 있습니다.
                </p>
              </section>
            ) : null}
            {authenticated && screen === "설정" && (
              <section>
                {publicService.access_mode === "public" && (
                  <>
                    <AccountSettings
                      request={request}
                      service={publicService}
                      onDeleted={disconnect}
                    />
                    <button
                      className="secondary"
                      disabled={busy}
                      onClick={() => void run(disconnect, "로그아웃했습니다.")}
                    >
                      로그아웃
                    </button>
                    <PublicFooter service={publicService} />
                  </>
                )}
                {(publicService.access_mode !== "public" || adminAccess) && (
                  <ProviderSettings
                    request={request}
                    onChanged={refreshAiAvailability}
                  />
                )}
                <UsageSettings request={request} />
                <ReferenceSettings
                  request={request}
                  refresh={() => refresh(ws?.id)}
                />
                <FactConflictReview
                  request={request}
                  refresh={() => refresh(ws?.id)}
                />
                <RuleControls request={request} />
                {adminAccess && (
                  <div className="admin-settings-entry">
                    <div>
                      <h3>관리자 페이지</h3>
                      <p className="muted">
                        내 계정의 운영 현황과 소스 저장소 연결을 확인합니다.
                      </p>
                    </div>
                    <button
                      className="secondary"
                      onClick={() => navigateScreen("관리자")}
                    >
                      관리자 페이지 열기 →
                    </button>
                  </div>
                )}
                <h3>내 데이터 관리</h3>
                {publicService.access_mode !== "public" && (
                  <button
                    disabled={busy}
                    onClick={() =>
                      void run(async () => {
                        await downloadPrivateExport(request);
                      }, "개인 자료 내려받기를 시작했습니다.")
                    }
                  >
                    내 자료 전체 내려받기
                  </button>
                )}
                <p className="muted">
                  원자료 삭제는 관련 근거를 무효화합니다. 이미 보관한 제출본은
                  과거 기록으로 유지됩니다. 제출본까지 지우려면 해당 지원 작업을
                  삭제하세요.
                </p>
                {Array.from(
                  new Map(evidence.map((e) => [e.source_id, e])).values(),
                ).map((e) => (
                  <div className="row" key={e.source_id}>
                    <span>{e.title}의 원자료</span>
                    <button
                      className="secondary"
                      disabled={busy}
                      onClick={() => {
                        if (
                          window.confirm(
                            "이 원자료를 삭제하고 연결된 근거를 무효화할까요?",
                          )
                        )
                          void run(async () => {
                            await request(
                              "/sources/" + e.source_id,
                              undefined,
                              "DELETE",
                            );
                            await refresh(ws?.id);
                          });
                      }}
                    >
                      원자료 삭제
                    </button>
                  </div>
                ))}
                <h3>지원 작업 삭제</h3>
                {list.map((w) => (
                  <div className="row" key={w.id}>
                    <span>
                      {w.company} · {w.role}
                    </span>
                    <button
                      className="secondary"
                      disabled={busy}
                      onClick={() => {
                        if (
                          window.confirm(
                            "지원 문서·제출 보관본·수정 기록을 모두 삭제할까요?",
                          )
                        )
                          void run(async () => {
                            await request(
                              "/applications/" + w.id,
                              undefined,
                              "DELETE",
                            );
                            if (ws?.id === w.id) setWs(null);
                            await refresh();
                          });
                      }}
                    >
                      작업 삭제
                    </button>
                  </div>
                ))}
              </section>
            )}
            {authenticated && screen === "관리자" && (
              <AdminConsole
                request={request}
                onSettings={() => navigateScreen("설정")}
                onOpenApplication={(id) =>
                  navigate(() => {
                    setScreen("지원 기회");
                    void run(() => refresh(id), "지원 작업을 열었습니다.");
                  })
                }
              />
            )}
            {authenticated && screen === "지원 기회" && !ws && (
              <>
                <OpportunityRankings
                  key={list.map((w) => w.id + w.state).join(":")}
                  request={request}
                  open={(id) => void refresh(id)}
                />
                <div className="stats-grid">
                  <div>
                    <span>준비 중인 지원</span>
                    <strong>
                      {
                        list.filter(
                          (w) => !["SUBMITTED", "CLOSED"].includes(w.state),
                        ).length
                      }
                      <small>개</small>
                    </strong>
                    <p>공고부터 최종 문서까지</p>
                  </div>
                  <div>
                    <span>사용 가능한 근거</span>
                    <strong>
                      {good.length}
                      <small>개</small>
                    </strong>
                    <p>확인한 경험·원자료</p>
                  </div>
                  <div>
                    <span>제출 완료</span>
                    <strong>
                      {
                        list.filter((w) =>
                          ["SUBMITTED", "CLOSED"].includes(w.state),
                        ).length
                      }
                      <small>개</small>
                    </strong>
                    <p>직접 제출을 확인한 지원</p>
                  </div>
                </div>
                {showCreate && (
                  <section className="create-card">
                    <div className="section-heading">
                      <h3>새로운 기회를 추가하세요</h3>
                      <span className="badge">STEP 01</span>
                    </div>
                    <form
                      onSubmit={submit(async (v) => {
                        const w = await request("/applications", {
                          company: v.company,
                          role: v.role,
                          jd_raw: v.jd,
                        });
                        await refresh(w.id);
                        setStage(stages[0]);
                        setShowCreate(false);
                      })}
                    >
                      <div className="grid">
                        <Field name="company" label="회사" />
                        <Field name="role" label="직무" />
                      </div>
                      <Field name="jd" label="채용 공고 내용" area />
                      <button disabled={busy}>지원 작업 만들기 →</button>
                    </form>
                  </section>
                )}
                <div className="dashboard-layout">
                  <section className="application-list">
                    <div className="section-heading">
                      <h2>
                        나의 지원 목록{" "}
                        <span className="total-count">{list.length}</span>
                      </h2>
                      <span className="muted">진행 현황</span>
                    </div>
                    <div className="list-toolbar">
                      <div className="filter-tabs" aria-label="지원 상태 필터">
                        {["전체", "준비 중", "제출 완료"].map((f) => (
                          <button
                            key={f}
                            className={filter === f ? "active" : ""}
                            aria-pressed={filter === f}
                            onClick={() => setFilter(f)}
                          >
                            {f}
                          </button>
                        ))}
                      </div>
                      <input
                        className="search"
                        aria-label="지원 목록 검색"
                        placeholder="회사 또는 직무 검색"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                      />
                    </div>
                    {filtered.length ? (
                      filtered.map((w) => (
                        <button
                          className="workspace-link"
                          key={w.id}
                          onClick={() =>
                            void run(async () => {
                              await refresh(w.id);
                              setStage(stages[0]);
                            }, "")
                          }
                        >
                          <span className="company-monogram">
                            {w.company
                              .replace(/\[.*?\]/g, "")
                              .trim()
                              .slice(0, 1)}
                          </span>
                          <span className="company-info">
                            <strong>{w.company}</strong>
                            <span>{w.role}</span>
                          </span>
                          <span
                            className={`badge ${w.state === "NEED_USER_ACTION" ? "stale" : ""}`}
                          >
                            {stateLabels[w.state] || "진행 중"}
                          </span>
                          <span className="arrow">↗</span>
                        </button>
                      ))
                    ) : (
                      <div className="empty-state">
                        <div className="empty-symbol">↗</div>
                        <h3>
                          {list.length
                            ? "검색 결과가 없습니다"
                            : "다음 기회가 시작되는 곳"}
                        </h3>
                        <p>
                          {list.length
                            ? "다른 검색어나 상태를 선택해 보세요."
                            : "관심 있는 채용 공고를 추가하면 준비 과정을 한곳에서 이어갈 수 있어요."}
                        </p>
                        {!list.length && (
                          <>
                            <ol className="first-workspace-guide">
                              <li>
                                ‘경험 정리’에서 내가 맡은 일과 수행 범위를
                                등록하세요.
                              </li>
                              <li>
                                회사·직무·채용 공고를 새 지원 기회에 넣으세요.
                              </li>
                              <li>
                                대화로 다음 단계를 진행하고, 오른쪽 보관함에서
                                문서를 확인하세요.
                              </li>
                            </ol>
                            <div className="public-actions">
                              <button
                                className="secondary"
                                onClick={() => setScreen("경험 정리")}
                              >
                                경험부터 정리하기
                              </button>
                              <button onClick={() => setShowCreate(true)}>
                                공고 추가하기
                              </button>
                            </div>
                          </>
                        )}
                      </div>
                    )}
                  </section>
                  <div className="dashboard-guide">
                    <section className="guide-card">
                      <span className="eyebrow">A CLEARER WAY FORWARD</span>
                      <h2>
                        좋은 지원서는
                        <br />내 경험에서 시작됩니다.
                      </h2>
                      <p>
                        확인된 근거를 쌓고, 공고에 맞는 메시지로 연결하세요.
                      </p>
                      <button
                        className="text-button"
                        onClick={() => setScreen("경험 정리")}
                      >
                        경험 정리하기 <span>→</span>
                      </button>
                    </section>
                    <div className="workflow-guide">
                      <h3>이렇게 진행해요</h3>
                      {[
                        "공고의 실제 업무 파악",
                        "경험과 핵심 메시지 연결",
                        "문서 작성과 근거 검수",
                        "최종본 보관 · 제출 확인",
                      ].map((label, i) => (
                        <div key={label}>
                          <span>{String(i + 1).padStart(2, "0")}</span>
                          {label}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </>
            )}
            {authenticated && screen === "경험 정리" && (
              <>
                <div className="row">
                  <p>원자료와 직접 수행한 범위를 함께 기록하세요.</p>
                  <button
                    className="secondary"
                    disabled={busy}
                    onClick={() =>
                      void run(async () => {
                        const r = await request("/sources/import", {});
                        await refresh();
                        setTrace(r);
                      }, "자료를 가져왔습니다. 확인 전 기록은 미검증 상태로 유지됩니다.")
                    }
                  >
                    첨부 팩의 자료 가져오기
                  </button>
                </div>
                <SourceUpload request={request} refresh={() => refresh()} />
                <KnowledgeSearch request={request} />
                <Panel title="경험·사실 등록">
                  <form
                    onSubmit={submit(async (v) => {
                      await request("/evidence", {
                        title: v.title,
                        body: v.body,
                        source_title: v.source,
                        ownership: v.ownership,
                        forbidden_claims: lines(v.forbidden),
                        confirmed: v.confirmed === "on",
                      });
                      await refresh();
                    })}
                  >
                    <div className="grid">
                      <Field name="title" label="프로젝트·경험 이름" />
                      <Field name="source" label="원자료 이름 / 출처" />
                    </div>
                    <Field
                      name="body"
                      label="실제 수행·관찰·성과 (수치의 범위도 포함)"
                      area
                    />
                    <label>
                      구현 범위
                      <select name="ownership">
                        <option value="UNKNOWN">아직 확인하지 않음</option>
                        <option value="USER">직접 구현</option>
                        <option value="USER_AI_ASSISTED">
                          AI 도움을 받아 구현
                        </option>
                        <option value="USER_MODIFIED_EXISTING_CODE">
                          기존 코드 수정
                        </option>
                        <option value="TEAM">팀 수행</option>
                        <option value="LAB">연구실 수행</option>
                      </select>
                    </label>
                    <Field
                      name="forbidden"
                      label="주장하면 안 되는 내용 (한 줄에 하나)"
                      area
                    />
                    <label className="check">
                      <input name="confirmed" type="checkbox" /> 원자료와 실제
                      수행 범위를 직접 확인했습니다.
                    </label>
                    <button disabled={busy}>근거 저장</button>
                  </form>
                </Panel>
                {evidence.map((e) => (
                  <details className="evidence-card" key={e.id}>
                    <summary className="row">
                      <strong>{e.title}</strong>
                      <span className="badge">
                        {e.status === "USER_CONFIRMED"
                          ? "직접 확인 완료"
                          : e.status === "UNVERIFIED"
                            ? "확인 필요"
                            : e.status === "SOURCE_BACKED"
                              ? "출처 확인"
                              : e.status === "VERIFIED"
                                ? "검증 완료"
                                : "표현 참고"}
                      </span>
                    </summary>
                    <div className="evidence-detail">
                      <p className="evidence-body">{e.body}</p>
                      {e.status === "UNVERIFIED" && e.kind !== "EXPRESSION" && (
                        <button
                          disabled={busy}
                          onClick={() =>
                            void run(async () => {
                              await request(`/evidence/${e.id}/confirm`, {
                                confirmed: true,
                              });
                              await refresh();
                            })
                          }
                        >
                          내용을 직접 확인하고 승인
                        </button>
                      )}
                      {e.kind !== "EXPRESSION" && (
                        <ProjectBoundary
                          evidence={e}
                          request={request}
                          refresh={() => refresh()}
                        />
                      )}
                      {e.kind !== "EXPRESSION" && (
                        <ExperienceStructure
                          evidence={e}
                          request={request}
                          ai={ai}
                          refresh={() => refresh()}
                        />
                      )}
                    </div>
                  </details>
                ))}
              </>
            )}
            {authenticated && screen === "검증 기록" && (
              <section>
                <h3>실제 작업 피드백</h3>
                <button
                  disabled={busy}
                  onClick={() =>
                    void run(async () => setTrace(await request("/telemetry")))
                  }
                >
                  기록 불러오기
                </button>
                {trace && <DataView data={trace} />}
                <p className="muted">
                  실사용 자료가 쌓이기 전에는 단계별 품질 향상 수치를 만들지
                  않습니다.
                </p>
              </section>
            )}
            {authenticated && screen === "지원 기회" && ws && (
              <>
                <ConversationWorkspace
                  key={ws.id}
                  send={api.send}
                  workspace={ws}
                  questionId={qid}
                  qSelect={setQid}
                  evidenceOptions={evidence.map((e) => ({
                    id: e.id,
                    title: e.title,
                  }))}
                  sourceNames={Object.fromEntries(
                    evidence.map((item) => [
                      item.source_id,
                      item.title + " 원자료",
                    ]),
                  )}
                  request={request}
                  refresh={refresh}
                  onBack={() => setWs(null)}
                  ai={ai}
                  renderArtifact={(a) => (
                    <>
                      <Card a={a} />
                      {["Draft", "ResumeContent"].includes(a.kind) && (
                        <ProvenancePanel artifactId={a.id} request={request} />
                      )}
                      {a.kind === "ResumeContent" && (
                        <>
                          <p className="muted">
                            분량 목표 · {resumeBudgetLabel(a.data)}
                          </p>
                          <ResumeFiles
                            workspaceId={ws.id}
                            artifactId={a.id}
                            send={api.send}
                          />
                        </>
                      )}
                    </>
                  )}
                  onEdit={(index, question) => {
                    setStage(stages[index]);
                    if (question !== undefined) setQid(question);
                    if (index === 3)
                      setResumePages(
                        String(resume ? resumeBudget(resume.data) || 1 : 1) as
                          "1" | "2" | "MASTER",
                      );
                    setShowEditor(true);
                  }}
                />
                {showEditor && (
                  <EditorDialog
                    ref={editorHandle}
                    key={`${ws.id}:${stage}:${stage === stages[2] ? qid : ""}`}
                    onClose={() => setShowEditor(false)}
                    request={request}
                    workspaceId={ws.id}
                    draftKey={`editor:${ws.id}:${stages.indexOf(stage)}:${stage === stages[2] ? qid : ""}`}
                    baseArtifactId={
                      latest(
                        stage === stages[3]
                          ? "ResumeContent"
                          : stage === stages[2]
                            ? "Draft"
                            : stage === stages[1]
                              ? "ApplicationBrief"
                              : "OpportunityBrief",
                        stage === stages[2] ? qid : "",
                      )?.id
                    }
                  >
                    <div className="editor-feedback">
                      {error && (
                        <p className="error" role="alert">
                          {error}
                        </p>
                      )}
                      {notice && (
                        <p className="note" role="status">
                          {notice}
                        </p>
                      )}
                    </div>
                    <div className="row">
                      <span
                        className={`badge ${ws.state === "NEED_USER_ACTION" ? "stale" : ""}`}
                      >
                        {stateLabels[ws.state] || ws.state}
                      </span>
                    </div>
                    <nav className="stage-nav" aria-label="지원 준비 단계">
                      {stages.map((s, i) => (
                        <button
                          className={stage === s ? "active" : ""}
                          aria-current={stage === s ? "step" : undefined}
                          key={s}
                          onClick={() => {
                            if (stage !== s) navigate(() => setStage(s));
                          }}
                        >
                          <span className="step-number">{i + 1}</span>
                          {s}
                        </button>
                      ))}
                    </nav>
                    {stage === stages[0] && (
                      <>
                        <ResearchStatus
                          research={latest("CompanyResearchResult")}
                          review={latest("ResearchReview")}
                        />
                        <ResearchPanel
                          research={latest("CompanyResearchResult")}
                          review={latest("ResearchReview")}
                          jd={ws.jd_raw}
                          ai={ai}
                          act={act}
                          editable={
                            ![
                              "SUBMISSION_FROZEN",
                              "SUBMITTED",
                              "CLOSED",
                            ].includes(ws.state)
                          }
                        />
                        <Card a={latest("OpportunityBrief")} />
                        <Panel
                          title="직무 분석"
                          open={!latest("OpportunityBrief")}
                        >
                          <p className="muted">
                            공고에서 실제 산출물과 본업을 정리하세요. 수동
                            입력은 직접 판단한 내용으로 저장됩니다.
                          </p>
                          <details>
                            <summary>등록한 공고</summary>
                            <pre>{ws.jd_raw}</pre>
                          </details>
                          {ai && button("AI로 직무 분석", "analyze")}
                          {button("회사 조사", "research", { live: ai })}
                          <form
                            onSubmit={submit((v) =>
                              act("analyze", {
                                manual: {
                                  ...(latest("OpportunityBrief")?.data || {}),
                                  company_facts: [
                                    ...((latest("CompanyResearchResult")?.data
                                      .official_facts || []) as Data[]),
                                    ...((latest("CompanyResearchResult")?.data
                                      .external_evidence || []) as Data[]),
                                  ],
                                  company_inferences:
                                    latest("CompanyResearchResult")?.data
                                      .inferences || [],
                                  actual_outputs: lines(v.outputs),
                                  base_profession: v.profession,
                                  main_skills: lines(v.skills),
                                  required: lines(v.required).map(
                                    (requirement) => ({
                                      requirement,
                                      source_id: "jd",
                                    }),
                                  ),
                                  preferred: lines(v.preferred).map(
                                    (requirement) => ({
                                      requirement,
                                      source_id: "jd",
                                    }),
                                  ),
                                  posting_status: v.posting_status,
                                  deadline_at: v.deadline_at,
                                  deadline_timezone: v.deadline_at
                                    ? v.deadline_timezone
                                    : "",
                                  verified_at:
                                    v.verified === "on"
                                      ? new Date().toISOString()
                                      : "",
                                  output_importance: lines(v.outputs).map(
                                    (output, i) => ({
                                      output,
                                      importance: v["importance" + i] || "CORE",
                                    }),
                                  ),
                                },
                              }),
                            )}
                          >
                            <Field
                              name="profession"
                              label="본업 / 직업 정체성"
                              value={String(
                                latest("OpportunityBrief")?.data
                                  .base_profession || ws.role,
                              )}
                            />
                            <Field
                              name="outputs"
                              label="실제 업무 산출물 (한 줄에 하나)"
                              value={(
                                (latest("OpportunityBrief")?.data
                                  .actual_outputs as string[]) || []
                              ).join("\n")}
                              area
                            />
                            <Field
                              name="skills"
                              label="핵심 역량 (한 줄에 하나)"
                              value={(
                                (latest("OpportunityBrief")?.data
                                  .main_skills as string[]) || []
                              ).join("\n")}
                              area
                            />
                            <Field
                              name="required"
                              label="필수 지원 조건 (한 줄에 하나)"
                              area
                              value={(
                                (latest("OpportunityBrief")?.data
                                  .required as Data[]) || []
                              )
                                .map((r) => String(r.requirement))
                                .join("\n")}
                            />
                            <Field
                              name="preferred"
                              label="우대 조건 (한 줄에 하나)"
                              area
                              value={(
                                (latest("OpportunityBrief")?.data
                                  .preferred as Data[]) || []
                              )
                                .map((r) => String(r.requirement))
                                .join("\n")}
                            />
                            <label>
                              채용 상태
                              <select
                                name="posting_status"
                                defaultValue={String(
                                  latest("OpportunityBrief")?.data
                                    .posting_status || "UNCERTAIN",
                                )}
                              >
                                <option value="UNCERTAIN">확인 필요</option>
                                <option value="OPEN">채용 중</option>
                                <option value="CLOSED">마감</option>
                              </select>
                            </label>
                            <Field
                              name="deadline_at"
                              label="마감 날짜·시각 (예: 2026-10-15T18:00:00+09:00)"
                              value={String(
                                latest("OpportunityBrief")?.data.deadline_at ||
                                  "",
                              )}
                            />
                            <Field
                              name="deadline_timezone"
                              label="마감 시간대"
                              value={String(
                                latest("OpportunityBrief")?.data
                                  .deadline_timezone || "Asia/Seoul",
                              )}
                            />
                            <label className="check">
                              <input name="verified" type="checkbox" />
                              현재 공고의 채용 상태를 직접 확인했습니다.
                            </label>
                            {(
                              (latest("OpportunityBrief")?.data
                                .actual_outputs as string[]) || []
                            ).map((output, i) => (
                              <label key={output}>
                                {output} 중요도
                                <select
                                  name={"importance" + i}
                                  defaultValue={String(
                                    (
                                      (latest("OpportunityBrief")?.data
                                        .output_importance as Data[]) || []
                                    ).find((o) => o.output === output)
                                      ?.importance || "CORE",
                                  )}
                                >
                                  <option value="CRITICAL">필수 핵심</option>
                                  <option value="CORE">주요 업무</option>
                                  <option value="SUPPORTING">보조 업무</option>
                                </select>
                              </label>
                            ))}
                            <button disabled={busy}>직무 분석 저장</button>
                          </form>
                        </Panel>
                        <Card a={latest("CompanyResearchResult")} />
                        <section>
                          <h3>직무와 경험 정리 연결</h3>
                          {!good.length && (
                            <p className="note">
                              먼저 ‘경험 정리’에서 확인된 경험을 등록해 주세요.
                            </p>
                          )}
                          {ai && button("AI로 근거 매핑", "evidence-map")}
                          <SemanticMapping
                            request={request}
                            workspaceId={ws.id}
                            outputs={
                              (latest("OpportunityBrief")?.data
                                .actual_outputs as string[]) || []
                            }
                            ai={ai}
                            refresh={() => refresh(ws.id)}
                          />
                          <form
                            onSubmit={submit((v) => {
                              const outputs =
                                (latest("OpportunityBrief")?.data
                                  .actual_outputs as string[]) || [];
                              return act("evidence-map", {
                                manual: {
                                  items: outputs.flatMap((o, i) =>
                                    v["e" + i]
                                      ? [
                                          {
                                            evidence_id: v["e" + i],
                                            job_output_id: o,
                                            classification: v["c" + i],
                                            evidence_strength: "MODERATE",
                                            ownership_strength: "LIMITED",
                                            rationale: v["r" + i],
                                          },
                                        ]
                                      : [],
                                  ),
                                  uncovered_outputs: [],
                                },
                              });
                            })}
                          >
                            {(
                              (latest("OpportunityBrief")?.data
                                .actual_outputs as string[]) || []
                            ).map((o, i) => (
                              <div className="mapping" key={o}>
                                <h4>{o}</h4>
                                <label>
                                  증명할 경험
                                  <select name={"e" + i}>
                                    <option value="">근거 없음</option>
                                    {good.map((e) => (
                                      <option key={e.id} value={e.id}>
                                        {e.title}
                                      </option>
                                    ))}
                                  </select>
                                </label>
                                <label>
                                  관계
                                  <select
                                    name={"c" + i}
                                    defaultValue="ADJACENT"
                                  >
                                    <option value="DIRECT">직접 증거</option>
                                    <option value="ADJACENT">인접 경험</option>
                                    <option value="NO_EVIDENCE">
                                      증거 아님
                                    </option>
                                  </select>
                                </label>
                                <Field
                                  name={"r" + i}
                                  label="이렇게 판단한 이유"
                                />
                              </div>
                            ))}
                            <button
                              disabled={busy || !latest("OpportunityBrief")}
                            >
                              근거 연결 저장
                            </button>
                          </form>
                        </section>
                        <Card a={latest("EvidencePack")} />
                        <AssessmentEditor
                          workspace={ws}
                          request={request}
                          refresh={() => refresh(ws.id)}
                          ai={ai}
                        />
                        <Card a={latest("OpportunityAssessment")} />
                      </>
                    )}
                    {stage === stages[1] && (
                      <>
                        <ExperienceOptions
                          ready={experienceReady}
                          workspaceId={ws.id}
                          slot="strategy"
                          version={ws.artifacts
                            .map((artifact) => artifact.id + artifact.status)
                            .join(":")}
                          request={request}
                          sourceNames={Object.fromEntries(
                            evidence.map((item) => [
                              item.source_id,
                              item.title + " 원자료",
                            ]),
                          )}
                          slotNames={Object.fromEntries(
                            questions.map((question, index) => [
                              question.id,
                              `${index + 1}번 · ${question.text}`,
                            ]),
                          )}
                          onSelected={async () => {
                            await refresh(ws.id);
                          }}
                        />
                        <Card a={latest("ApplicationBrief")} />
                        <Panel title="지원 전략 설계" open>
                          {ai && button("AI 전략 제안", "strategy")}
                          <form
                            onSubmit={submit((v) =>
                              act("strategy", {
                                manual: {
                                  positioning: v.positioning,
                                  base_profession_identity: v.profession,
                                  main_skill_message: v.main,
                                  differentiator_message: v.diff,
                                  assignment_statement: v.assignment,
                                  fatal_gaps: lines(v.gaps),
                                  fatal_gap_strategy: v.gapplan,
                                  selection_risks: lines(v.risks),
                                },
                              }),
                            )}
                          >
                            <Field
                              name="profession"
                              label="본업 정체성"
                              value={ws.role}
                            />
                            <Field
                              name="positioning"
                              label="어떤 지원자로 기억되어야 하나요?"
                            />
                            <Field name="main" label="핵심 역량 메시지" />
                            <Field name="diff" label="차별점" />
                            <Field
                              name="assignment"
                              label="입사 후 실제 맡길 수 있는 일"
                            />
                            <Field name="gaps" label="부족한 근거" area />
                            <Field name="gapplan" label="한계에 대한 대응" />
                            <Field name="risks" label="전형 리스크" area />
                            <button disabled={busy}>전략 제안 저장</button>
                          </form>
                          {button(
                            "이 전략으로 진행",
                            "approve-strategy",
                            {},
                            ws.state !== "WAITING_STRATEGY_APPROVAL",
                          )}
                        </Panel>
                      </>
                    )}
                    {stage === stages[2] && (
                      <>
                        <Panel title="문항 추가">
                          <form
                            onSubmit={submit(async (v) => {
                              await act("add-question", {
                                text: v.question,
                                limit: Number(v.limit),
                              });
                            })}
                          >
                            <Field name="question" label="질문" />
                            <Field
                              name="limit"
                              label="글자 수 제한 (공백 포함)"
                              type="number"
                              value="1000"
                            />
                            <button disabled={busy}>문항 추가</button>
                          </form>
                          <label>
                            작업할 문항
                            <select
                              value={qid}
                              data-draft-ignore
                              onChange={(e) => {
                                const id = e.target.value;
                                navigate(() => setQid(id));
                              }}
                            >
                              <option value="">선택하세요</option>
                              {questions.map((q) => (
                                <option key={q.id} value={q.id}>
                                  {q.text}
                                </option>
                              ))}
                            </select>
                          </label>
                        </Panel>
                        {qid && (
                          <>
                            <ExperienceOptions
                              ready={experienceReady}
                              key={qid}
                              workspaceId={ws.id}
                              slot={qid}
                              version={ws.artifacts
                                .map(
                                  (artifact) => artifact.id + artifact.status,
                                )
                                .join(":")}
                              request={request}
                              sourceNames={Object.fromEntries(
                                evidence.map((item) => [
                                  item.source_id,
                                  item.title + " 원자료",
                                ]),
                              )}
                              slotNames={Object.fromEntries(
                                questions.map((question, index) => [
                                  question.id,
                                  `${index + 1}번 · ${question.text}`,
                                ]),
                              )}
                              onSelected={async () => {
                                await refresh(ws.id);
                              }}
                            />
                            <Card a={brief} />
                            <Panel title="문항 메시지와 근거" open>
                              {ai &&
                                button("AI 문항 설계", "question-brief", {
                                  qid,
                                })}
                              <form
                                key={qid}
                                onSubmit={submit((v) =>
                                  act("question-brief", {
                                    qid,
                                    manual: {
                                      question_id: qid,
                                      question_type: v.type,
                                      evaluation_intent: v.intent,
                                      primary_message: v.message,
                                      evidence_ids: Array.from(
                                        new Set([
                                          v.evidence,
                                          ...Object.entries(v)
                                            .filter(
                                              ([key, value]) =>
                                                key.startsWith("supporting_") &&
                                                value === "on",
                                            )
                                            .map(([key]) =>
                                              key.slice("supporting_".length),
                                            ),
                                        ]),
                                      ),
                                      supporting_claims: (v.claims || "")
                                        .split("\n")
                                        .map((s) => s.trim())
                                        .filter(Boolean),
                                      decision: v.decision,
                                      insight: v.insight,
                                      job_relevance: v.relevance,
                                      operational_value: v.operational_value,
                                      value_scope: v.value_scope,
                                      expression_angle: v.expression_angle,
                                    },
                                  }),
                                )}
                              >
                                <label>
                                  문항 유형
                                  <select name="type">
                                    <option value="JOB_COMPETENCY">
                                      직무 역량
                                    </option>
                                    <option value="MOTIVATION">
                                      지원 동기
                                    </option>
                                    <option value="VALUES">가치관</option>
                                    <option value="COLLABORATION">협업</option>
                                    <option value="CHALLENGE">도전</option>
                                    <option value="STRENGTH_WEAKNESS">
                                      강점·약점
                                    </option>
                                    <option value="OTHER">포부·기타</option>
                                  </select>
                                </label>
                                <Field name="intent" label="평가하려는 것" />
                                <Field
                                  name="message"
                                  label="이 문항에서 남길 핵심 메시지"
                                />
                                <label>
                                  주된 경험
                                  <select
                                    name="evidence"
                                    key={
                                      latest("ExperienceSelection", qid)?.id ||
                                      qid
                                    }
                                    defaultValue={String(
                                      latest("ExperienceSelection", qid)?.data
                                        .evidence_id || "",
                                    )}
                                  >
                                    {good
                                      .filter((e) =>
                                        (
                                          (latest("EvidencePack")?.data
                                            .items as Data[]) || []
                                        ).some(
                                          (i) =>
                                            i.evidence_id === e.id &&
                                            i.classification !== "NO_EVIDENCE",
                                        ),
                                      )
                                      .map((e) => (
                                        <option key={e.id} value={e.id}>
                                          {e.title}
                                        </option>
                                      ))}
                                  </select>
                                </label>
                                <details>
                                  <summary>
                                    같은 메시지를 뒷받침하는 경험 추가
                                  </summary>
                                  <p className="muted">
                                    경험이 여러 개여도 이 문항의 핵심 메시지는
                                    하나로 유지합니다.
                                  </p>
                                  {good
                                    .filter((e) =>
                                      (
                                        (latest("EvidencePack")?.data
                                          .items as Data[]) || []
                                      ).some(
                                        (i) =>
                                          i.evidence_id === e.id &&
                                          i.classification !== "NO_EVIDENCE",
                                      ),
                                    )
                                    .map((e) => (
                                      <label className="check" key={e.id}>
                                        <input
                                          type="checkbox"
                                          name={`supporting_${e.id}`}
                                        />
                                        {e.title}
                                      </label>
                                    ))}
                                </details>
                                <Field
                                  name="claims"
                                  label="뒷받침 주장 (한 줄에 하나씩)"
                                  area
                                />
                                <Field name="decision" label="핵심 판단" />
                                <Field
                                  name="insight"
                                  label="경험에서 배운 점"
                                />
                                <Field name="relevance" label="직무와의 연결" />
                                <Field
                                  name="operational_value"
                                  label="어떤 점검·위험·판단을 돕는가?"
                                  area
                                  value={String(
                                    brief?.data.operational_value || "",
                                  )}
                                />
                                <label>
                                  성과 표현 범위
                                  <select
                                    name="value_scope"
                                    defaultValue={String(
                                      brief?.data.value_scope ||
                                        "OPERATIONAL_POSSIBILITY",
                                    )}
                                  >
                                    <option value="OPERATIONAL_POSSIBILITY">
                                      운영 적용 가능성
                                    </option>
                                    <option value="TECHNICAL_RESULT">
                                      검증한 기술 결과
                                    </option>
                                    <option value="MEASURED_BUSINESS_IMPACT">
                                      실제 운영에서 측정한 업무 성과
                                    </option>
                                  </select>
                                </label>
                                <label>
                                  표현 관점
                                  <select
                                    name="expression_angle"
                                    defaultValue={String(
                                      brief?.data.expression_angle ||
                                        "구현과 산출물",
                                    )}
                                  >
                                    <option>구현과 산출물</option>
                                    <option>운영가치</option>
                                    <option>문제 재정의</option>
                                    <option>제약과 설계 판단</option>
                                    <option>핵심 메시지</option>
                                    <option>검증 근거</option>
                                  </select>
                                </label>
                                <button disabled={busy}>문항 설계 저장</button>
                              </form>
                              {brief &&
                                ["ACTIVE", "LOCKED"].includes(brief.status) && (
                                  <ClaimEvidencePanel
                                    key={brief.id}
                                    workspaceId={ws.id}
                                    brief={brief}
                                    result={latest("ClaimEvidenceTest", qid)}
                                    ai={ai}
                                    request={request}
                                    act={act}
                                  />
                                )}
                              {button(
                                "메시지 승인·잠금",
                                "approve-question",
                                { qid },
                                !brief ||
                                  brief.status !== "ACTIVE" ||
                                  latest("ClaimEvidenceTest", qid)?.data
                                    .result !== "PASSED" ||
                                  latest("ClaimEvidenceTest", qid)?.data
                                    .brief_id !== brief.id ||
                                  !["ACTIVE", "LOCKED"].includes(
                                    latest("ClaimEvidenceTest", qid)?.status ||
                                      "",
                                  ),
                              )}
                            </Panel>
                            <Card a={draft} />
                            {draft && (
                              <ProvenancePanel
                                artifactId={draft.id}
                                request={request}
                              />
                            )}
                            <section>
                              <h3>본문 작성</h3>
                              {ai &&
                                button(
                                  "승인된 근거로 AI 작성",
                                  "generate",
                                  { qid },
                                  brief?.status !== "LOCKED",
                                )}
                              <form
                                onSubmit={submit((v) => {
                                  if (v.confirmed !== "on")
                                    throw new Error(
                                      "주장과 근거를 확인해 주세요.",
                                    );
                                  return act("generate", {
                                    qid,
                                    manual: manualDocument(v.text, selected),
                                  });
                                })}
                              >
                                <Field
                                  name="text"
                                  label="직접 작성한 본문 (줄마다 주장을 구분하면 검토하기 쉽습니다)"
                                  area
                                  value={String(draft?.data.text || "")}
                                />
                                <label className="check">
                                  <input name="confirmed" type="checkbox" /> 각
                                  문장의 사실·수치·수행 범위가 선택 근거에
                                  있음을 확인했습니다.
                                </label>
                                <button
                                  disabled={busy || brief?.status !== "LOCKED"}
                                >
                                  초안 저장
                                </button>
                              </form>
                            </section>
                            {draft && (
                              <>
                                <Panel title="필요한 부분만 수정">
                                  <form
                                    onSubmit={submit((v) =>
                                      act("patch", {
                                        qid,
                                        old_text: v.old,
                                        new_text: v.new,
                                        protected: lines(v.protected),
                                      }),
                                    )}
                                  >
                                    <Field name="old" label="바꿀 원문" />
                                    <Field name="new" label="교체할 문장" />
                                    <Field
                                      name="protected"
                                      label="보호할 문장 (한 줄에 하나)"
                                      area
                                      value={(
                                        (draft.data
                                          .protected_spans as string[]) || []
                                      ).join("\n")}
                                    />
                                    <button disabled={busy}>
                                      부분 수정 저장
                                    </button>
                                  </form>
                                  <p className="muted">
                                    본문을 바꾸면 검수가 무효화됩니다. 수정된
                                    내용의 근거를 확인하고 아래에서 주장 연결을
                                    갱신하세요.
                                  </p>
                                  <button
                                    disabled={busy}
                                    onClick={() =>
                                      void run(() =>
                                        act("ledger", {
                                          qid,
                                          claims: manualDocument(
                                            String(draft.data.text),
                                            selected,
                                          ).claims,
                                        }),
                                      )
                                    }
                                  >
                                    현재 본문의 모든 주장·수행 범위를 직접
                                    확인하고 갱신
                                  </button>
                                </Panel>
                                <section>
                                  <h3>검수와 최종 잠금</h3>
                                  {ai &&
                                    button(
                                      "AI 사실·채용담당자 검수",
                                      "review",
                                      {
                                        qid,
                                      },
                                    )}
                                  {ai &&
                                    button(
                                      "검수 의견으로 AI 수정 제안",
                                      "revise",
                                      {
                                        qid,
                                      },
                                    )}
                                  {button(
                                    "모든 문장을 직접 검토했음 · 검수 기록",
                                    "review",
                                    { qid, manual_verified: true },
                                  )}
                                  {button(
                                    "현재 검수 결과로 최종 잠금",
                                    "final-lock",
                                    {
                                      qid,
                                    },
                                    !responsesComplete(
                                      latest("Review", qid),
                                      latest("ReviewResponses", qid),
                                    ),
                                  )}
                                  <p className="muted">
                                    직접 검수 모드에서도 근거에 없는 숫자와 사용
                                    금지 주장은 차단합니다.
                                  </p>
                                </section>
                                <Card a={latest("Review", qid)} />
                                <ReviewResponsePanel
                                  workspaceId={ws.id}
                                  review={latest("Review", qid)}
                                  result={latest("ReviewResponses", qid)}
                                  ai={ai}
                                  request={request}
                                  act={act}
                                  editable={
                                    ![
                                      "SUBMISSION_FROZEN",
                                      "SUBMITTED",
                                      "CLOSED",
                                    ].includes(ws.state)
                                  }
                                />
                                <ExpressionLibrary
                                  key={`${ws.id}:${draft?.id || "cover"}`}
                                  document={draft}
                                  domain="COVER"
                                  workspaceId={ws.id}
                                  request={request}
                                  act={act}
                                  evidence={evidence}
                                />
                              </>
                            )}
                          </>
                        )}
                      </>
                    )}
                    {stage === stages[3] && (
                      <>
                        <ExperienceOptions
                          ready={experienceReady}
                          workspaceId={ws.id}
                          slot="resume"
                          version={ws.artifacts
                            .map((artifact) => artifact.id + artifact.status)
                            .join(":")}
                          request={request}
                          sourceNames={Object.fromEntries(
                            evidence.map((item) => [
                              item.source_id,
                              item.title + " 원자료",
                            ]),
                          )}
                          slotNames={Object.fromEntries(
                            questions.map((question, index) => [
                              question.id,
                              `${index + 1}번 · ${question.text}`,
                            ]),
                          )}
                          onSelected={async () => {
                            await refresh(ws.id);
                          }}
                        />
                        <Card a={latest("ResumeBrief")} />
                        <Card a={resume} />
                        {resume && (
                          <>
                            <p className="muted">
                              현재 분량 목표 · {resumeBudgetLabel(resume.data)}
                            </p>
                            <ProvenancePanel
                              artifactId={resume.id}
                              request={request}
                            />
                            <ResumeFiles
                              workspaceId={ws.id}
                              artifactId={resume.id}
                              send={api.send}
                            />
                          </>
                        )}
                        <section>
                          <h3>이력서 작성</h3>
                          <p>
                            직접 증거를 먼저 보여주고, 각 항목은
                            산출물·행동·근거 순으로 작성하세요.
                          </p>
                          <form
                            onSubmit={submit((v) => {
                              if (v.confirmed !== "on")
                                throw new Error("근거 확인이 필요합니다.");
                              const ids = (
                                (latest("EvidencePack")?.data
                                  .items as Data[]) || []
                              )
                                .filter(
                                  (i) => i.classification !== "NO_EVIDENCE",
                                )
                                .map((i) => String(i.evidence_id));
                              return act("resume", {
                                manual: manualDocument(v.text, ids),
                                page_budget:
                                  v.pages === "MASTER"
                                    ? "MASTER"
                                    : Number(v.pages),
                              });
                            })}
                          >
                            <label>
                              분량 목표
                              <select
                                name="pages"
                                value={resumePages}
                                onChange={(event) =>
                                  setResumePages(
                                    event.target.value as "1" | "2" | "MASTER",
                                  )
                                }
                              >
                                <option value="1">1페이지 선택형</option>
                                <option value="2">2페이지 선택형</option>
                                <option value="MASTER">전체 경력 마스터</option>
                              </select>
                            </label>
                            {ai &&
                              button("AI 이력서 작성", "resume", {
                                page_budget:
                                  resumePages === "MASTER"
                                    ? "MASTER"
                                    : Number(resumePages),
                              })}
                            <Field
                              name="text"
                              label="이력서 본문"
                              area
                              value={String(resume?.data.text || "")}
                            />
                            <label className="check">
                              <input name="confirmed" type="checkbox" /> 현재
                              근거 매핑으로 모든 항목과 수행 범위를
                              확인했습니다.
                            </label>
                            <button disabled={busy}>이력서 저장</button>
                          </form>
                          {resume && (
                            <>
                              <button
                                className="secondary"
                                disabled={busy}
                                onClick={() =>
                                  void run(
                                    () =>
                                      request(
                                        `/applications/${ws.id}/resume/file-qa`,
                                        {
                                          artifact_id: resume.id,
                                          confirmed: true,
                                        },
                                      ),
                                    "현재 버전의 파일 검토를 기록했습니다.",
                                  )
                                }
                              >
                                실제 파일의 잘림·페이지·링크·날짜를 직접
                                확인했음
                              </button>
                              {resume.status === "LOCKED" && (
                                <button
                                  className="secondary"
                                  disabled={busy}
                                  onClick={() =>
                                    void run(
                                      () =>
                                        request("/resume-master", {
                                          artifact_id: resume.id,
                                          confirmed: true,
                                        }),
                                      "검토한 이력서를 재사용할 마스터로 저장했습니다.",
                                    )
                                  }
                                >
                                  이 이력서를 마스터로 사용
                                </button>
                              )}
                              {ai &&
                                button("AI 이력서 검수", "review", {
                                  resume: true,
                                })}
                              {button("이력서를 직접 검토했음", "review", {
                                resume: true,
                                manual_verified: true,
                              })}
                              {button(
                                "이력서 최종 잠금",
                                "final-lock",
                                {
                                  resume: true,
                                },
                                !responsesComplete(
                                  latest("ResumeReview"),
                                  latest("ResumeReviewResponses"),
                                ),
                              )}
                              <button
                                className="secondary"
                                onClick={() => {
                                  const link = document.createElement("a");
                                  link.href = URL.createObjectURL(
                                    new Blob([String(resume.data.text)], {
                                      type: "text/markdown;charset=utf-8",
                                    }),
                                  );
                                  link.download = "resume.md";
                                  link.click();
                                  URL.revokeObjectURL(link.href);
                                }}
                              >
                                Markdown 내려받기
                              </button>
                              <button
                                className="secondary"
                                onClick={() =>
                                  void run(async () => {
                                    const response = await api.send(
                                      `/applications/${ws.id}/resume/preview`,
                                    );
                                    if (!response.ok)
                                      throw new Error(
                                        "이력서 미리보기를 불러오지 못했습니다.",
                                      );
                                    const url = URL.createObjectURL(
                                      new Blob([await response.text()], {
                                        type: "text/html;charset=utf-8",
                                      }),
                                    );
                                    const link = document.createElement("a");
                                    link.href = url;
                                    link.download = "resume-preview.html";
                                    link.click();
                                    setTimeout(
                                      () => URL.revokeObjectURL(url),
                                      1000,
                                    );
                                  }, "이력서 미리보기 파일을 만들었습니다.")
                                }
                              >
                                HTML 미리보기 내려받기
                              </button>
                            </>
                          )}
                        </section>
                        <Card a={latest("ResumeReview")} />
                        <ReviewResponsePanel
                          workspaceId={ws.id}
                          review={latest("ResumeReview")}
                          result={latest("ResumeReviewResponses")}
                          ai={ai}
                          request={request}
                          act={act}
                          editable={
                            ![
                              "SUBMISSION_FROZEN",
                              "SUBMITTED",
                              "CLOSED",
                            ].includes(ws.state)
                          }
                        />
                        <ExpressionLibrary
                          key={`${ws.id}:${resume?.id || "resume"}`}
                          document={resume}
                          domain="RESUME"
                          workspaceId={ws.id}
                          request={request}
                          act={act}
                          evidence={evidence}
                        />
                      </>
                    )}
                    <RevisionInbox
                      workspace={ws}
                      request={request}
                      refresh={() => refresh(ws.id)}
                    />
                    <CorrectionInbox
                      workspace={ws}
                      request={request}
                      refresh={() => refresh(ws.id)}
                    />
                    {stage === stages[4] && (
                      <>
                        <FinalReview
                          workspaceId={ws.id}
                          revision={ws.artifacts
                            .map((a) => `${a.id}:${a.status}`)
                            .join(",")}
                          frozen={[
                            "SUBMISSION_FROZEN",
                            "SUBMITTED",
                            "CLOSED",
                          ].includes(ws.state)}
                          request={request}
                          act={act}
                        />
                        <section>
                          <h3>최종 점검</h3>
                          <p>
                            요청한 문항과 이력서를 모두 검수하고 잠근 후
                            제출본을 보관합니다.
                          </p>
                          {button("전체 잠금·중복 메시지 확인", "ready")}
                          {button(
                            "문서 간 사실·수치·반복 검사",
                            "portfolio-review",
                            { manual_verified: !ai },
                          )}
                          {button(
                            "최종본 보관 · 아직 미제출",
                            "freeze",
                            {},
                            ws.state !== "READY_TO_FREEZE",
                          )}
                          {button(
                            "실제 제출을 완료했음",
                            "confirm",
                            { confirmed: true },
                            ws.state !== "SUBMISSION_FROZEN",
                          )}
                          {ws.data.submitted_at && (
                            <p>제출 확인 시각: {ws.data.submitted_at}</p>
                          )}
                          {ws.data.closed_at && (
                            <p>추적 종료 시각: {ws.data.closed_at}</p>
                          )}
                        </section>
                        {latest("SubmissionBundle") && (
                          <section>
                            <h3>보관된 최종본</h3>
                            <p>
                              보관 시각:{" "}
                              {String(
                                latest("SubmissionBundle")?.data.frozen_at,
                              )}
                            </p>
                            <p>
                              이 보관본은 수정되지 않습니다. 실제 제출 확인은
                              별도 기록됩니다.
                            </p>
                          </section>
                        )}
                        {ws.artifacts
                          .filter(
                            (a) =>
                              [
                                "Review",
                                "ResumeReview",
                                "PortfolioReview",
                              ].includes(a.kind) && a.status !== "SUPERSEDED",
                          )
                          .map((a) => (
                            <Card key={a.id} a={a} />
                          ))}
                      </>
                    )}
                    {stage === stages[5] && (
                      <>
                        <section>
                          <h3>제출본으로 면접 준비</h3>
                          {button(
                            "면접 준비 자료 만들기",
                            "interview-handoff",
                            {},
                            !latest("SubmissionBundle"),
                          )}
                        </section>
                        <Card a={latest("InterviewHandoff")} />
                        <Panel title="전형 결과 기록">
                          <form
                            onSubmit={submit((v) =>
                              act("outcome", {
                                result: v.result,
                                notes: v.notes,
                              }),
                            )}
                          >
                            <label>
                              결과
                              <select name="result">
                                <option value="DOCUMENT_PASS">서류 합격</option>
                                <option value="DOCUMENT_FAIL">서류 탈락</option>
                                <option value="CODING_FAIL">
                                  코딩 테스트 탈락
                                </option>
                                <option value="ASSESSMENT_FAIL">
                                  적성 검사 탈락
                                </option>
                                <option value="INTERVIEW_FAIL">
                                  면접 탈락
                                </option>
                                <option value="FINAL_OFFER">최종 합격</option>
                                <option value="UNKNOWN">미확인</option>
                              </select>
                            </label>
                            <Field
                              name="notes"
                              label="확인된 이유 / 메모"
                              area
                            />
                            <button disabled={busy}>결과 저장</button>
                          </form>
                          {button("전형별 회고 만들기", "postmortem")}
                          {ai &&
                            button("AI로 회고 가설 검토", "postmortem", {
                              draft_hypotheses: true,
                            })}
                        </Panel>
                        <Card a={latest("Postmortem")} />
                        {["SUBMITTED", "CLOSED"].includes(ws.state) && (
                          <Panel title="지원 추적 종료">
                            {ws.state === "CLOSED" ? (
                              <>
                                <p>종료 시각: {ws.data.closed_at}</p>
                                {ws.data.closure_reason && (
                                  <p>{ws.data.closure_reason}</p>
                                )}
                                <p className="muted">
                                  제출본과 전형 기록은 계속 확인할 수 있습니다.
                                </p>
                              </>
                            ) : (
                              <form
                                onSubmit={submit((v) => {
                                  if (v.confirmed !== "on")
                                    throw new Error(
                                      "지원 추적 종료를 확인해 주세요.",
                                    );
                                  return act("close", {
                                    confirmed: true,
                                    reason: v.reason || "",
                                  });
                                })}
                              >
                                <Field
                                  name="reason"
                                  label="종료 메모 (선택)"
                                  area
                                />
                                <label className="check">
                                  <input name="confirmed" type="checkbox" /> 이
                                  지원의 전형 추적을 종료합니다.
                                </label>
                                <p className="muted">
                                  제출본과 전형 기록을 보관합니다.
                                </p>
                                <button disabled={busy}>
                                  추적 종료하고 기록 보관
                                </button>
                              </form>
                            )}
                          </Panel>
                        )}
                      </>
                    )}
                    <Panel title="근거 정정 · 작업 수정">
                      <p className="muted">
                        선택한 문항과 근거를 대상으로 저장된 상태를 바꿉니다.
                      </p>
                      <form
                        onSubmit={submit((v) =>
                          act("commands", {
                            text: v.command,
                            qid,
                            evidence_id: v.evidence,
                          }),
                        )}
                      >
                        <label>
                          대상 근거
                          <select name="evidence">
                            <option value="">없음</option>
                            {evidence.map((e) => (
                              <option key={e.id} value={e.id}>
                                {e.title}
                              </option>
                            ))}
                          </select>
                        </label>
                        <Field
                          name="command"
                          label="명령 (예: 이건 Adjacent / RAG 빼 / 이 수치 틀림)"
                        />
                        <button disabled={busy}>수정 반영</button>
                      </form>
                    </Panel>
                  </EditorDialog>
                )}
              </>
            )}
            <footer>Career Harness / 경험을 근거로, 다음 기회로.</footer>
          </article>
        </main>
      </ReviewFeedback.Provider>
    </ReferenceNames.Provider>
  );
}
