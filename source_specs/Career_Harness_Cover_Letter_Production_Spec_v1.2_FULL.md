# Career Harness — 자기소개서 PART Production Specification v1.2 FULL

작성 기준: 2026-09-28
상태: Canonical Draft for Implementation
범위: 지원 전 판단 → 회사/직무 분석 → Evidence/Claim 설계 → 자기소개서 작성 → 검수 → 제출 → 면접 인계 → 전형 결과 → 사후분석 → 규칙 개선

## 0. 시스템이 재현해야 하는 실제 작업방식

1. 공고가 나와 맞는지 먼저 판단한다.
2. JD의 기술 키워드가 아니라 실제 본업과 Output을 해석한다.
3. 그 일을 내가 실제로 해봤는지 Direct / Adjacent / No Evidence로 나눈다.
4. 프로젝트 원자료와 잠금본을 다시 확인해 Fact / Ownership / Metric / Limitation을 잠근다.
5. 과거 자소서는 Fact가 아니라 표현과 사고방식을 참고하는 자료로 쓴다.
6. GPT가 바로 완성문을 쓰지 않고, 중간 판단을 사용자에게 보여준다.
7. 사용자가 “아니다”, “이건 Adjacent”, “RAG 빼”, “이 메시지로 가자”라고 수정하면 구조화된 상태 자체가 바뀐다.
8. 회사별 Positioning과 전체 문항 Portfolio를 먼저 설계한다.
9. 각 문항은 Primary Message를 잠근 뒤 작성한다.
10. 작성 후 Fact / Ownership / 면접 Reverse Test / 채용담당자 Red Team을 거친다.
11. 최종 제출본은 문항별 잠금 메시지, 전체 캐릭터, 면접 주의사항과 함께 스냅샷으로 저장한다.
12. 서류 합격/탈락, 코테 탈락, 면접 탈락을 구분해 결과를 저장한다.
13. 탈락했다고 무조건 자소서 규칙을 고치지 않는다.
14. 결과와 사용자의 반복 correction에서만 Candidate Rule을 만들고 검증 후 승격한다.

핵심 철학:
- Write after proof.
- Decide before write.
- Persona is derived, not imposed.
- Keyword match is not job fit.
- Fact and expression are different data.
- A rejection is not automatically a writing failure.
- User corrections modify structured artifacts, not only chat text.
- Outcome learning must be stage-aware.
- Important claims must be traceable to evidence and ownership.

---

# 1. 전체 라이프사이클

```text
BEFORE APPLICATION
JD
→ Pre-Application Fit Gate
→ Company / Job Reality
→ Capability Match
→ Evidence Mapping
→ Application Strategy
→ [Human Gate A]

WRITING
Question Portfolio
→ Question Intent
→ Fact Retrieval + Expression Retrieval
→ Claim Design
→ [Human Gate B]
→ Writer
→ Hard / Semantic QA
→ Reverse Interview
→ Recruiter / Red Team
→ Cross-Question Portfolio QA
→ Final

AFTER WRITING
Submission Snapshot
→ Interview Handoff
→ Selection Stage Outcome
→ Application Postmortem
→ Correction / Outcome Analysis
→ Candidate Rule
→ Historical Eval
→ User Approval
→ Canonical Rule
```

항상 옆에서 `Conversational Artifact Editing`이 동작한다.

---

# 2. 사용자 UX는 6단계만 노출

## UX 0 — 지원할 가치가 있나?
- Base Profession Fit
- Main Skill Coverage
- Direct Evidence Count
- Fatal Gap
- 면접/코테 등 전형 리스크
- Proceed / Proceed with Gap / Low Priority

## UX 1 — 직무 이해
- Actual Output
- Base Profession
- Specialty
- Tool
- Main Skill
- Differentiator
- Hiring Context

## UX 2 — 내 증거
- Direct Evidence
- Adjacent Evidence
- No Evidence
- Ownership
- Evidence Strength
- Verification Status
- Claim Boundary

## UX 3 — 지원 전략
- Assignment Statement
- Positioning
- Fatal Gap Strategy
- Question Portfolio
- Human Gate A

## UX 4 — 문항 작성
- Question Intent
- Primary Message
- Supporting Claims
- Evidence
- Style Reference
- Draft
- Human Gate B

## UX 5 — 검수 / 제출 / 후속
- Fact QA
- Ownership QA
- Reverse Interview
- Recruiter Rejection Risks
- Cross-Question QA
- Final
- Submission Snapshot
- Interview Handoff
- Outcome / Postmortem

---

# 3. Pre-Application Fit Gate

평가 순서:
1. Base Profession Fit
2. Actual Output Fit
3. Main Skill Evidence Coverage
4. Direct Evidence Count
5. Fatal Gap
6. Interview Defensibility
7. 전형 생존 리스크
8. 추가 준비 비용

예시:
```json
{
  "decision": "PROCEED_WITH_GAP",
  "actual_outputs": 3,
  "direct_evidence_count": 2,
  "adjacent_evidence_count": 1,
  "fatal_gaps": ["production serving"],
  "selection_risks": ["coding test"],
  "reason": "본업 3개 중 2개는 직접 증명 가능하나 production 운영 경험은 부족함"
}
```

금지:
- RAG/Agent 키워드 일치만 보고 높은 적합도 부여
- Differentiator를 Main Skill Evidence로 계산
- 코테/면접 생존 가능성을 무시

---

# 4. Capability Profile

강점/약점을 prompt에 영구 하드코딩하지 않는다.

```json
{
  "capability_id": "production_ai",
  "name": "Production AI Engineering",
  "level": "DEVELOPING",
  "confidence": 0.72,
  "evidence_ids": [],
  "gap_evidence_ids": [],
  "last_updated": "",
  "source": ""
}
```

예상 카테고리:
- Problem Discovery
- Problem Structuring
- Data Analysis
- Signal / Metric Design
- Evaluation
- Failure Diagnosis
- Python / SQL
- Backend Engineering
- API Development
- Production Serving
- Data Engineering
- Distributed Systems
- Domain Knowledge
- Stakeholder Collaboration

새 경험이 생기면 Profile도 갱신한다.

---

# 5. 데이터 층

## Fact Store
- CareerFact
- Project
- Experience
- Decision
- Hypothesis
- Observation
- Metric
- Ownership
- Limitation
- ClaimBoundary
- Source

## Expression Store
- Past Final Answer
- Accepted Phrase
- Rejected Phrase
- User Correction
- Tone Preference
- Motivation Pattern
- Value Pattern
- Question-type Pattern
- Locked Message

## Rule Store
- Writing Rule
- Career Rule
- Claim Rule
- Project Rule
- Industry Rule
- Company-specific Rule
- User Preference

## Outcome Store
- Application Outcome
- Stage
- Date
- Known reason
- Unknown reason
- Postmortem Hypotheses
- Attribution scope

---

# 6. Fact Verification Status

- VERIFIED
- USER_CONFIRMED
- SOURCE_BACKED
- UNVERIFIED
- CONFLICTED
- SUPERSEDED
- DO_NOT_USE

Writer 기본 사용 가능:
VERIFIED / USER_CONFIRMED / SOURCE_BACKED

UNVERIFIED는 사용자 확인 또는 source 보강.
CONFLICTED는 Truth Resolver.
SUPERSEDED는 기록용.
DO_NOT_USE는 생성에서 제외.

---

# 7. Source Authority

우선순위:
1. 현재 사용자의 명시적 정정
2. 최신 잠금본
3. Master Resume / 프로젝트 원자료
4. 과거 최종 지원서
5. 과거 대화
6. 일반 추론

Retrieval top-1이 Truth를 결정하지 않는다.

---

# 8. Decision / Experiment Graph

프로젝트의 핵심을 의사결정 흐름으로 저장한다.

노드:
- Problem
- Constraint
- Initial Hypothesis
- Alternative
- Experiment
- Observation
- Unexpected Result
- Rejected Hypothesis
- Reduced Claim
- Reframing
- Decision
- Action
- Validation
- Result
- Limitation
- Insight

예:
```text
Hypothesis
→ tested_by → Experiment
→ produced → Observation
→ contradicted → Hypothesis
→ caused → Reframing
→ led_to → Decision
```

지원하는 검색:
- 예상과 다른 결과를 보고 판단을 바꾼 경험
- 기존 방법을 버린 경험
- 실패에서 문제를 재정의한 경험
- 비용/현실 제약 때문에 설계를 바꾼 경험
- 가설을 축소한 경험

Negative Result를 1급 Evidence로 취급한다.

---

# 9. Metric Ledger

```json
{
  "metric_id": "",
  "project_id": "",
  "name": "",
  "value": null,
  "unit": "",
  "dataset": "",
  "subset": "",
  "time_scope": "",
  "experiment_version": "",
  "baseline": "",
  "denominator": "",
  "interpretation": "",
  "source_id": "",
  "valid_for_claims": [],
  "invalid_for_claims": []
}
```

규칙:
- 숫자보다 의미를 먼저 쓴다.
- 최신/과거 실험 버전을 구분한다.
- subset metric을 전체 성과처럼 확대하지 않는다.
- baseline 없는 개선율을 만들지 않는다.
- 측정하지 않은 생산성 수치를 생성하지 않는다.

---

# 10. Ownership Model

```json
{
  "evidence_id": "face_decision_pipeline",
  "ownership": {
    "problem_discovery": "USER",
    "problem_definition": "USER",
    "architecture": "USER",
    "implementation": "USER_AI_ASSISTED",
    "integration": "USER_MODIFIED_EXISTING_CODE",
    "team_result": "TEAM"
  }
}
```

값:
- USER
- USER_AI_ASSISTED
- USER_MODIFIED_EXISTING_CODE
- TEAM
- LAB
- UNKNOWN

AI coding tool 사용을 숨기지 않는다.
판단과 구현 보조를 구분한다.

---

# 11. Expression Sanitization

과거 자소서 원문을 Writer에게 그대로 넘기지 않는다.

Expression Retrieval → StyleProjection → Writer

```json
{
  "question_type": "MOTIVATION",
  "logic_pattern": [
    "개인 경험에서 생긴 기준",
    "본업 선택",
    "회사 고유 사실",
    "현실적 성장"
  ],
  "tone": ["담백함", "사람다운 표현", "기술설명 최소"],
  "preferred_patterns": [],
  "avoid_patterns": ["회사 칭찬 나열", "AI식 추상 교훈"]
}
```

회사명, 날짜, 수치, 학력, 과거 상태 등 Fact는 제거하거나 재검증한다.

---

# 12. Retrieval

v0.1:
- PostgreSQL
- FTS
- Metadata filtering

v0.2+:
- FTS
- pgvector
- Metadata
- Source authority
- Verification status
- Freshness

개념적 ranking:
`semantic relevance × authority × validity × freshness`

Truth는 별도 canonical resolution.

---

# 13. Company / Job Reality

조사:
- 최신 JD
- 회사 사업 / 수익 구조
- 조직/직무 실제 업무
- 유사/과거/경력직 JD
- 현직자 인터뷰
- 실제 프로젝트/업무
- 회사가 지금 이 직무를 뽑는 이유

회사 정보 타입:
- OFFICIAL_FACT
- EXTERNAL_EVIDENCE
- INFERENCE

Inference를 회사 공식 사실처럼 Writer에게 넘기지 않는다.

---

# 14. Role Identity

반드시:
- Base Profession
- Specialty
- Tool
- Role Noun

Role Noun Test:
자기소개서를 다 읽은 채용담당자가 떠올리는 첫 직업 명사가 Base Profession과 맞아야 한다.

---

# 15. Main Skill / Differentiator

Main Skill:
회사가 실제로 돈을 주고 시키는 일.

Differentiator:
그 일을 더 잘하게 만드는 차별점.

Differentiator로 Main Skill 부족을 덮지 않는다.

---

# 16. Evidence Mapping

Direct / Adjacent / No Evidence는 관계 속성이다.

```json
{
  "job_output_id": "",
  "evidence_id": "",
  "classification": "DIRECT",
  "evidence_strength": 4,
  "ownership_strength": 4,
  "verification_status": "VERIFIED",
  "claim_boundaries": []
}
```

---

# 17. Fatal Gap Audit

분류:
- FATAL
- MANAGEABLE
- COMPENSATABLE
- DEVELOPMENTAL

포함:
- 어떤 Main Skill과 연결되는지
- 숨기면 안 되는지
- 다른 Evidence로 보완 가능한지
- 면접 리스크
- 입사 후 성장 계획과 연결 가능한지

---

# 18. Assignment Statement

반드시:
> “입사 후 실제로 이 지원자에게 맡길 수 있는 일은 ______이다.”

구체적 답이 없으면 Positioning 미확정.

---

# 19. Application Strategy

```json
{
  "positioning": "",
  "base_profession_identity": "",
  "main_skill_message": "",
  "differentiator_message": "",
  "fatal_gap_strategy": "",
  "assignment_statement": "",
  "do_not_position_as": []
}
```

Persona는 여기서 도출한다.

---

# 20. Question Portfolio

각 문항:
- Evaluation Intent
- Identity Role
- Primary Message Candidate
- Evidence Candidate
- Avoided Repetition

같은 프로젝트 재사용 허용.
같은 Fact / 숫자 / 결론 / Primary Message 반복 금지.

---

# 21. Conversational Artifact Editing

자연어 수정이 구조화된 Artifact를 바꾼다.

예:
- “이건 Adjacent임” → EvidenceMap 수정
- “RAG 빼” → ClaimLock/Evidence 수정
- “본업은 개발보다 기획 같아” → RoleIdentity 수정 + downstream STALE
- “이 메시지 좋음. 잠가” → ClaimLock LOCKED
- “이 수치 80% 아니야” → MetricLedger 수정 + 의존 Artifact STALE

변경 후 시스템은 어떤 Artifact가 바뀌었는지 보여준다.

---

# 22. Human Gate A — Strategy Lock

승인 대상:
- Role Identity
- Main Skill
- Differentiator
- Fatal Gap
- Assignment Statement
- Positioning
- Question Portfolio

승인 전 Writer 금지.

---

# 23. Question Intent

- MOTIVATION
- JOB_COMPETENCY
- VALUES
- COLLABORATION
- CHALLENGE
- STRENGTH_WEAKNESS
- OTHER

구조화 output.
Jev 후보 가능.

---

# 24. Claim Lock

```json
{
  "primary_message": "",
  "supporting_claims": [],
  "evidence_ids": [],
  "decision": "",
  "insight": "",
  "job_relevance": "",
  "forbidden_claims": []
}
```

Primary Message는 하나.
Supporting Claims/Evidence는 여러 개 가능.

---

# 25. Human Gate B — Claim Lock

- Approve
- Edit Primary Message
- Edit Supporting Claims
- Replace Evidence
- Remove Experience

승인 전 Writer 금지.

---

# 26. Question-type Skills

Motivation:
내 경험에서 생긴 기준 → 산업 본업 → 회사 → 회사 고유 사실 → 본업 학습 → 전문성 확장

Job Competency:
Main Skill → 왜 필요한가 → Evidence → Decision → Metric/Outcome → 현재 Gap → 회사 적용

Values:
가치관 → 반복 판단 기준 → 형성 계기 → 최근 사례 → 실제 선택 → 현재 습관 → 회사 행동

Collaboration:
공동 목표 → 불일치 원인 → 기준/정보 정렬 → 조정 → 공동 결과 → 업무 적용

Challenge:
어려움 → 초기 접근 → 예상 밖 결과 → Turning Point → Reframing → 결과 → 판단 변화

Strength/Weakness:
반복 행동 패턴 + Evidence + 직무 가치 /
실제 약점 + 문제 방식 + 현재 관리 시스템

---

# 27. Writer Responsibility

Writer는 자유 탐색 Agent가 아니다.

입력:
- Job Reality
- Application Strategy
- Question Intent
- ClaimLock
- Selected Evidence
- StyleProjection
- Claim Boundaries
- Character Limit

금지:
- 새로운 Fact
- 새로운 Metric
- Ownership 확대
- 새로운 회사 사실
- Fatal Gap 은폐
- Claim Boundary 위반

Writer는 compiler에 가깝다.

---

# 28. QA

## Hard QA — Code
- character count
- source exists
- metric exists
- canonical fact conflict
- superseded / DO_NOT_USE fact
- stale dependency
- explicit forbidden claim
- user isolation
- missing provenance

## Semantic Grounding
Claim:
- SUPPORTED
- PARTIALLY_SUPPORTED
- UNSUPPORTED

## Ownership QA
Draft 동사와 Ownership metadata 대조.

## Reverse Interview
- 왜 정의했나?
- 왜 이 방법인가?
- 대안은?
- 어떤 관찰이 방향을 바꿨나?
- 한계는?
- 본인 역할은?
- 숫자의 범위는?
하이브리드 직무는 본업 의지까지 확인.

## Recruiter Red Team
“내가 채용담당자라면 왜 떨어뜨릴까?”
구체적인 rejection risk를 출력.

---

# 29. Cross-Question Portfolio QA

검사:
- 같은 Primary Message 반복
- 같은 수치 반복
- 같은 프로젝트를 같은 각도로 반복
- 문항 역할 침범
- 전 문항이 AI 이야기만 하는지
- Base Profession / 협업 / 가치관 / 전문성이 입체적으로 보이는지
- 전체를 읽고 맡길 일이 보이는지

---

# 30. Revision / Compression

Revision 우선순위:
P0 Fact/Ownership
P1 Claim/Job Fit
P2 Main Skill/Positioning
P3 Message Clarity
P4 Portfolio Balance
P5 Readability
P6 Style

자동 revision 최대 2회.

Compression 삭제:
1. 기술 스택
2. 중요하지 않은 과정
3. 중복
4. 반복 결과
5. 일반론
6. 회사 칭찬
7. 수식어

보존:
1. 질문 답
2. 본업 선택 이유
3. Decision
4. Evidence
5. Insight
6. 회사 고유 근거
7. Job Relevance
8. 현실적 성장

---

# 31. Submission Snapshot

실제 제출 시 immutable snapshot 생성:

- Company
- Role
- JD version
- Resume version
- Final Questions/Answers
- Application Positioning
- Question Portfolio
- Claim Locks
- Evidence IDs
- Metric IDs
- Known Gaps
- Claim Boundaries
- submitted_at

---

# 32. Interview Handoff Pack

Submission Snapshot으로 생성:

- 문항별 핵심 Claim
- 예상 꼬리질문
- Reverse Interview 질문
- 정확한 Ownership
- 사용한 숫자와 범위
- 과장 금지 포인트
- Fatal Gap에 대한 솔직한 답
- 회사 본업 관련 질문
- 프로젝트별 1/3/5분 설명

---

# 33. Selection Stage Outcome

- DOCUMENT_PASS
- DOCUMENT_FAIL
- ASSESSMENT_PASS
- ASSESSMENT_FAIL
- CODING_PASS
- CODING_FAIL
- INTERVIEW_PASS
- INTERVIEW_FAIL
- FINAL_OFFER
- WITHDRAWN
- UNKNOWN

CODING_FAIL을 자기소개서 실패로 학습하지 않는다.

---

# 34. Application Postmortem

Outcome
→ 당시 JD 복원
→ Actual Output 재검토
→ 제출 문서 역매핑
→ Direct / Adjacent / No Evidence
→ Main Skill / Differentiator 균형
→ Fatal Gap 노출 여부
→ Question Intent 적합성
→ Claim Defensibility
→ Postmortem Hypotheses

“탈락 원인”으로 단정하지 않는다.

```json
{
  "type": "MAIN_SKILL_MISMATCH",
  "observation": "평가/진단 Evidence는 강하나 Agent 구현 Evidence는 상대적으로 약함",
  "confidence": "MEDIUM",
  "attribution_scope": "DOCUMENT"
}
```

---

# 35. Outcome Attribution Guard

DOCUMENT_FAIL:
서류 Fit/Evidence/Strategy/Claim/Writing 후보 업데이트 가능.

CODING_FAIL / ASSESSMENT_FAIL:
자소서 Rule 자동 업데이트 금지.

INTERVIEW_FAIL:
Interview Defensibility / Handoff / Claim depth 후보 업데이트 가능.

FINAL_OFFER:
긍정 signal이나 특정 문장 때문이라고 단정하지 않음.

---

# 36. Correction Memory

User Edit에서 후보 추출:
- Fact Correction
- Preference
- Writing Rule
- Claim Boundary
- Style Pattern
- Positioning Preference
- Evidence Classification Correction

자동 Canonical 반영 금지.

---

# 37. Rule Scope / Promotion

Scope:
- GLOBAL
- USER
- INDUSTRY
- ROLE_TYPE
- QUESTION_TYPE
- PROJECT
- COMPANY

Promotion:
Observation
→ Candidate Rule
→ 반복 Correction/Outcome Evidence
→ Historical Eval
→ User Approval
→ Canonical Rule

하나의 사례를 global rule로 과승격하지 않는다.

---

# 38. Conversational Command Semantics

“ㄱㄱ”
→ 현재 workflow의 다음 단계 실행. Writer 강제 호출 아님.

“이걸로 가자”
→ current proposal approve

“잠가”
→ current Artifact LOCKED

“다시”
→ current stage regenerate + downstream STALE

“이건 아니야”
→ correction capture

“RAG 말고 교통”
→ Evidence replacement

“이건 내가 한 거 아님”
→ Ownership correction + downstream STALE

---

# 39. Artifact / Staleness

Artifact:
- ACTIVE
- LOCKED
- STALE
- SUPERSEDED
- INVALID

JD 변경:
JobReality 새 버전
→ EvidenceMap/Strategy/Claim/Draft/Review STALE

Metric correction:
→ 해당 Metric 사용 Claim/Draft/Review STALE

Ownership correction:
→ 관련 Claim/Draft/Interview Pack STALE

---

# 40. Jev / Decision Layer

```text
DecisionModel
├── LLMStructuredDecisionProvider
└── JevDecisionProvider
```

초기:
LLM Structured = primary
Jev = shadow

Jev 우선 후보:
- Question Type
- Role Noun alignment
- 질문 직접 응답 여부
- 기술 나열 과다
- Revision routing
- Binary/Choice QA

신중:
- Direct/Adjacent/No Evidence
- Semantic Grounding
- Ownership semantic match

제외:
- Fatal Gap
- Positioning
- Strategy
- Claim Design
- Writing

Human vs LLM vs Jev eval 후 검증된 task만 primary 승격.

---

# 41. Stage-Level Eval

- Fit Eval
- Job Reality Eval
- Evidence Eval
- Strategy Eval
- Claim Eval
- Draft Eval
- Reviewer Eval
- Postmortem Attribution Eval

Reviewer도 evaluation 대상이다.

---

# 42. Historical Regression Dataset

```json
{
  "input_context": {},
  "bad_ai_output": "",
  "user_correction": "",
  "correction_reason": "",
  "accepted_output": "",
  "rule_candidate": "",
  "stage": ""
}
```

대표 유형:
- 오래된 Fact
- 졸업상태 오류
- Main Skill/Differentiator 역전
- 기술 나열
- Persona 선고정
- Ownership 과장
- Claim Boundary 위반
- 회사 칭찬형 지원동기
- 사용자 Message 무시
- AI식 추상 교훈
- Expression DB fact contamination
- 제출 완료 임의 추론
- 탈락 stage 잘못 귀속
- Reviewer over-correction

---

# 43. Product Metrics

최상위:
- Decision Acceptance Rate
- Final User Edit Distance

추가:
- Evidence Replacement Rate
- Strategy Rejection Rate
- Claim Rejection Rate
- Unsupported Claim Rate
- Ownership Error Rate
- Metric Context Error Rate
- Revision Count
- Portfolio Duplication Rate
- Time to Final
- Cost per Application
- Outcome Attribution Error
- Candidate Rule Promotion Precision
- Stale Artifact Regeneration Count
- Jev / LLM Disagreement

---

# 44. Observability / Versioning

저장:
- run_id
- application_id
- question_id
- stage
- input_artifact_ids
- output_artifact_id
- provider
- model
- prompt_version
- token_usage
- cost
- latency
- status
- error

주요 prompt versioning:
fit_gate / job_reality / evidence_mapper / strategy / claim_designer / writer / reverse_interviewer / recruiter_redteam / postmortem

Prompt 변경 시 regression eval.

---

# 45. Cost / Failure / Privacy

Stage별 비용/latency budget을 둔다.
비싼 모델을 전 stage에 쓰지 않는다.

Provider failure:
- RETRYABLE
- PROVIDER_UNAVAILABLE
- PARTIAL_COMPLETE
- NEED_USER_ACTION
- fallback provider

개인정보:
source 삭제 시 파생 Fact/Artifact 영향 분석 후 invalidation/stale propagation.
Workspace 전체 삭제 지원.
Raw exports/credentials repository commit 금지.

---

# 46. Workbench UI

Header:
Company / Role / Deadline / Current Stage / Selection Status

Stages:
1. Fit
2. Job
3. Evidence
4. Strategy
5. Questions
6. Review
7. Submission
8. Outcome

옆에 Assistant Chat.
Chat 수정은 Artifact patch로 연결한다.

---

# 47. Release Plan

## v0.1 — Personal End-to-End
- Pre-Application Fit Gate
- Workspace
- Fact/Expression Store
- Capability Profile
- Source Authority
- Verification Status
- Basic Retrieval
- Decision Graph
- Metric Ledger
- Job Reality
- Evidence Mapping
- Strategy Gate
- Claim Gate
- Writer
- QA
- Reverse Interview
- Recruiter Red Team
- Cross-Question QA
- Submission Snapshot
- Interview Handoff
- Artifact version/stale
- Conversational editing

## v0.2 — Outcome / Postmortem
- Selection Stage Outcome
- Application Postmortem
- Outcome Attribution Guard

## v0.3 — Correction / Rule Governance
- Correction Memory
- Candidate Rules
- Scoped Rules
- Rule Promotion

## v0.4 — Jev Shadow
## v0.5 — Selective Jev
## v1.0 — Multi-user Production

---

# 48. Explicit Non-Goals

- Autonomous application submission
- 자유토론형 Multi-Agent
- unlimited revision loops
- Fine-tuning
- 자체 LLM hosting
- Kubernetes
- 대규모 외부 vector DB
- 자동 Rule self-modification
- Outcome 하나로 자동 Rule 변경
- 탈락 원인 단정
- 모든 회사 사이트 자동 crawling
- AI가 사용자 대신 지원 여부 최종 결정

---

# 49. Definition of Done — 작업방식 재현

다음이 실제 가능해야 한다.

1. 새 공고를 넣는다.
2. 시스템이 먼저 Fit을 분석한다.
3. 사용자가 “백엔드 비중 너무 큰데?”라고 수정한다.
4. Job Reality가 수정되고 downstream이 갱신된다.
5. 프로젝트 원재료에서 Evidence를 찾는다.
6. 키워드상 비슷해도 Adjacent 판정이 가능하다.
7. “이건 내가 직접 한 게 아니다”라고 Ownership 수정 가능하다.
8. 관련 Claim/Draft가 STALE 된다.
9. 전체 지원 전략과 Question Portfolio가 나온다.
10. “이 회사에서는 데이터 분석형으로 보이자” 같은 수정이 가능하다.
11. Strategy가 LOCK된다.
12. 각 문항에서 Claim을 먼저 본다.
13. “OCR 빼고 MAS만” 같은 수정이 가능하다.
14. Claim LOCK 뒤에만 Writer가 쓴다.
15. Writer는 Fact/Metric/Ownership을 새로 만들 수 없다.
16. Fact/Ownership/Reverse Interview/Red Team을 통과한다.
17. 전체 문항 중복과 캐릭터 균형을 검사한다.
18. 실제 제출본이 Snapshot으로 잠긴다.
19. 동일 근거로 Interview Handoff가 생성된다.
20. 결과가 DOCUMENT_FAIL/CODING_FAIL/INTERVIEW_FAIL 등으로 저장된다.
21. CODING_FAIL이면 자소서 규칙을 고치지 않는다.
22. DOCUMENT_FAIL이면 Postmortem Hypothesis를 만든다.
23. 반복 correction과 outcome에서 Candidate Rule을 만든다.
24. Historical Eval과 사용자 승인을 통과한 Rule만 Canonical로 승격한다.
25. 다음 회사에 최신 Fact/Rule이 적용된다.

이 25개가 동작하면 실제 사용자-GPT 취업 작업방식이 시스템에 구조적으로 재현된 것으로 본다.

---

# 50. 한 줄 정의

> Career Harness는 글을 대신 써주는 AI가 아니라, 지원 판단부터 근거·전략·문장·면접·결과 학습까지 사용자의 실제 취업 의사결정 방식을 구조화하고 반복 가능하게 만드는 AI 작업 시스템이다.
