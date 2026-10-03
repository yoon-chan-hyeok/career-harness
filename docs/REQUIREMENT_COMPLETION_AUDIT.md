# 요구사항별 구현·수용 감사

> 2026-10-03 후속 사용자 결정: [USER_DECISIONS](USER_DECISIONS.md)에 따라 아래 과거 감사의 B0~B3 비교·성능 개선·확신 보정 실험 요구는 이번 출시 조건에서 제외한다. 레쥬메와 무료 생성 연결을 포함하며 HF/Groq 공식 어댑터, 개인 연결 설정, 25개 역할 지시문과 Jev 확신도 영속화를 추가했다. 아래 185개 검사·외부 수용 목록은 2026-10-02 기준이다. 최신 검사 수와 실제 연결 상태는 [현재 구현 보고](../IMPLEMENTATION_REPORT.md), `IMPLEMENTATION_STATUS.json`과 `work/free-service-tests.xml`을 확인한다. HF 플러그인 연결은 앱의 추론 토큰 등록이나 실모델 작성 검증을 뜻하지 않는다.

2026-10-02. v2.2 FINAL의 TASK-000~014, docs/00~15·05A·06A, source_specs 전체 요구, 추가 자료 6종 및 후속 사용자 요청을 대조했다. 사용자 지시가 원본 UI 구성보다 우선한다. 첨부 문서는 구현 자료이며 시스템 권한을 갖지 않는다.

**명세가 허용한 로컬·수동·테스트 제공자 범위의 구현은 완료했다. 공개 서비스 출시와 실모델 품질 수용은 완료하지 않았다.** 기존 감사에서 발견한 코드 누락은 아래 구현으로 보완했다. 외부 계정이나 키가 없다는 이유로 코드 누락을 완료로 표시하지 않는다.

## 실행 증거

- Python **185 통과 / 2 미실행**. 실제 PostgreSQL/pgvector·RLS 검사 2개는 TEST_POSTGRES_URL이 없다. 결과: `work/final-tests.xml`.
- Ruff 통과, 프로젝트 Python을 명시한 Pyright 0 오류. 웹 lint·TypeScript·Next.js 15.5.26 production build, Supabase 세션 갱신·회전·프로젝트 격리·로그아웃 검사 4개 통과.
- 실제 SQLite DB Alembic **0008 head**, `alembic check` 변경 없음. 빈 DB 왕복과 기존 데이터 backfill 검사 통과.
- 별도 QA 계정의 실제 HTTP 요청 **19개**로 승인→실패→수동 복구→검수→잠금→freeze→handoff→제출 확인→결과→회고→CLOSED 확인. 같은 재시도 키는 새 문서를 만들지 않고 보관본은 불변이다. `work/activity-e2e-audit.json`.
- 실제 브라우저: 저장 문서 열기·전략 승인, 문항 역할 계획 열기·후보·승인, 완료/확인 대기/실패 기록, 재연결, 390px 보관함 닫기·가로 넘침 없음. RUNNING의 별도 세션 관측·동시 실행 차단·중단 회수·늦은 결과 차단은 `test_activity.py`로 확인했다. 실제 장시간 모델 호출의 화면 캡처를 검증한 것으로 확대하지 않는다.
- 실제 DB를 새 백업에 저장하고 **별도 빈 대상**으로 복구: checksum·무결성·모든 테이블 행 수 일치, 브라우저 번들에 개인 토큰 없음. `work/local-recovery-audit.json`.
- 원본 추가 자료 6종·해시 보존, 예시 Fact/Evidence 미주입, 별도 QA 계정 격리. `work/supplemental-final-audit.json`.

## TASK / milestone 수용

| 범위 | 구현·검사 근거 | 외부/사람 수용 |
|---|---|---|
| M0 / TASK-001 | FastAPI·Next·Compose·Dockerfile·CI·0008, test_migrations, 실제 로컬 서버 | Docker가 없어 실제 3개 컨테이너 미실행 |
| M1 / TASK-000 | hard QA·PromptRun·Feedback·hash/usage/cost/latency/failure, test_qa_telemetry/runtime_trace/activity | 실사용 관측 |
| M2 / TASK-002 | 타입별 권위·정정·격리·Canonical·평가된 learned rule, test_domain/promotion_postmortem | 실제 사실의 사람 확인 |
| M3 / TASK-003 | 재귀 JSON/JSONL/TXT/MD·중복·충돌·빈 폴더·rollback, test_truth_import/regression_edges | DOCX/PDF는 optional later |
| M4 / TASK-004 | FTS/pgvector·task output/skill/decision reranking·사실/표현 분리, test_retrieval/task_retrieval | 실제 PostgreSQL. SQLite는 어휘 검색 |
| M5 / TASK-005 | manual/OpenAI/Fake research·추론·출처·날짜·과거 신호·JD hash·Fit gate, test_research/supplemental | 실검색 현재성·인용·해석 품질 |
| M6 / TASK-006 | 전략/Claim 승인·선택 근거·본문 ledger coverage·보호 문장·부분 수정 2회·병렬 Fact/Recruiter·조건부 Reverse, test_workflow/ledger_coverage/parallel_qa/company_claims | 의미상 사실·설득력·면접 방어 품질 |
| M7 / TASK-007 | versioned QuestionPortfolio 역할/의도/1~3 후보/근거/승인·다문항 기본 gate·전체 QA, test_portfolio_plan/document_qa | 의미 중복·캐릭터 균형의 사람 수용 |
| M8 / TASK-008 | Main Skill·Direct·업무 중요도·Ownership·산출물·최근 확인 순위·section order/budget·profile·HTML/Markdown, test_resume_layout/profile_resume | 물리 페이지·실제 파일 확인. PDF/DOCX optional |
| M9 / TASK-009 | exact commands·자유 Role/Positioning patch의 전후 제안/승인/현재 버전/stale·REST retry, test_structured_corrections/idempotency | 자유 문장 해석 품질 |
| M10 / TASK-010 | 불변 freeze·별도 제출 확인·frozen Claim/Metric/Ownership/gap·1/3/5 설명·CLOSED, test_interview_defense/close_application | 실제 발화 시간·미확인 대안/계획 |
| M11 / TASK-011 | frozen JD/문서/업무×근거/Claim 회고·선택적 AI LOW 가설·코테 작성 원인 금지·반복 교정 후보, test_promotion_postmortem/learned_proposal | 실제 원인·평가 자료 |
| M12 / TASK-012 | 실제 Workflow B0~B3 격리 실행·부분 수정·rule-specific 역사 평가·버전/사례/dataset/승인 검증, test_workflow_evaluation/historical_runner | 동의한 실호출·사람 labels. 품질 개선 주장 없음 |
| M13 / TASK-013 | choose/score/binary·5개 allowlist·official HTTP shadow·timeout/불일치/usage/장애 격리, test_decisions_evaluation/runtime_trace | 실제 Jev·비용·확신 보정·agreement. primary 승격 없음 |
| M14 / TASK-014 | chat+storage+agent 보기·Supabase JWKS/세션 회전·운영 guards/RLS/readiness/backup·Vercel 설정·read-only MCP, test_production_security/database_backup/mcp_protocol·브라우저 | 실제 Supabase/Vercel/backend/HTTPS/운영 DB/복구 |

## source_specs Definition of Done 25개

| 번호 | 구현 확인 | 수용 한계 |
|---|---|---|
| 1 | JD workspace 생성 | 실제 공고 입력/검색 확인 |
| 2 | 기본 ㄱㄱ에서 EvidencePack 다음 자격/Fit/우선순위 평가 | 명시적 수동 API는 사람이 입력한 별도 경로 |
| 3~4 | Job Reality 자유 구조 교정·승인·새 버전·stale | 모델 해석 품질 |
| 5~6 | task retrieval와 Direct/Adjacent 매핑 | 검색 우선순위는 Direct 증명이 아님 |
| 7~8 | 수행 범위 정정·확인 전 상태·관련 문서 stale | 과거 제출본 불변 |
| 9 | ApplicationBrief + 상세 QuestionPortfolio 배분 | 다문항 기본 진행은 계획 승인 먼저 |
| 10 | Positioning 자유 구조 교정·별도 승인 | 원자료/회사 사실/JD 자동 수정 없음 |
| 11 | Strategy LOCKED·이전 버전 승인 거절 | 사람 결정 |
| 12~14 | Claim/QuestionBrief→근거 교체→승인→Writer | 보호 문장·미확인 근거 차단 |
| 15 | 선택 Evidence/Profile/현재 회사 출처·수치/Ownership·본문 ledger coverage | coverage는 의미상 참의 증명이 아니며 Fact/Reverse·사람 검수 필요 |
| 16 | Fact/Ownership·Recruiter 병렬·조건부 Reverse/RedTeam | 실모델 품질 대기 |
| 17 | 전체 중복·프로젝트 다른 역할·수치/메시지 충돌 검수 | 의미/균형 사람 수용 |
| 18 | 불변 snapshot + 별도 제출 확인 | 자동 외부 제출 없음 |
| 19 | frozen facts와 회사 출처 기반 Handoff | 미확인 분모/대안/계획은 확인 필요 |
| 20~22 | 전형별 결과·coding no writing rule·LOW 가설 | 결과만으로 원인/합격률 단정 안 함 |
| 23 | ≥2 독립 교정에서 rule 후보 제안·중복 방지 | 결과 하나는 승격 근거가 아님 |
| 24 | 실제 writer/reviewer 역사 평가 저장·현재 버전/사례/dataset 검증·명시 승격 | caller passed 플래그로 승격 불가. 외부 평가 동의 필요 |
| 25 | 최신 Fact·범위가 맞는 유효 승인 Rule만 다음 회사에 사용 | 정정/삭제·구식 learned rule 제외 |

## 세부 명세와 구현 차이

docs/02~04의 Decision Graph는 `decision_graph.py`의 출처 연결 node/edge/원문 인용/관계 승인/무효화 투영으로 구현했다. EPISODE_NEXT는 순서이며 인과가 아니다. docs/05A의 작업 중 상태는 영속 ExecutionRun, 승인/검수/제출은 workspace·question·resume 상태에 기록한다. 자유 교정은 `structured_corrections.py`, 상세 Handoff는 `interview_defense.py`, 병렬 검수는 `parallel_qa.py`다.

docs/06/06A의 표현/사실·과거/현재 분리를 유지한다. docs/07 단계별 모델·시간·토큰·명시 가격 정책은 `provider_policy.py`; trace는 hash와 운영 metadata만 저장한다. docs/08~11 제품 비교는 `workflow_evaluation.py`, 반복 교정·검증·승격은 `promotion.py`다. 회사 FACT는 개인 경험 ID 대신 company_source_ids로 현재 출처의 정확한 원문에 연결하며 개인 Metric으로 전용하지 못한다. docs/12 REST aliases의 retry, docs/13 UI 승인/storage, docs/14 계정 경계, docs/15 사전 점검·로컬 복구를 확인했다.

## 실제 출시까지 남은 수용

1. Supabase PostgreSQL/Auth/JWKS를 실제 연결하고 두 사용자 로그인·갱신·격리·RLS를 확인한다.
2. backend container·HTTPS ingress·Vercel BACKEND_URL build/deploy에서 전체 흐름을 실행한다.
3. 실제 OpenAI/Jev의 허용 모델·예산·현재 가격을 설정하고 동의한 자료로 품질·장애·비용을 측정한다.
4. PostgreSQL 별도 빈 복구 대상, Auth 계정 유지, secret/CA/backup 보관을 함께 검증한다. SQLite 복구 성공으로 대신하지 않는다.

외부 계정·키 없이 할 수 있는 구현과 운영 연결 준비는 완료했다. 실행 절차는 `docs/PRODUCTION_DEPLOYMENT.md`, 가격 정책은 `docs/PROVIDER_BUDGETS.md`에 있다. 실서비스 운영 수용을 통과했다고 기록하지 않는다.
