# I03 — 문항 조건·가이드 선택·작성계획 연결

2026-10-23 사용자의 후속 진행 요청에 따라 통합 handoff I03만 구현한다. 기반은 `codex/i02-scoped-context`의 `9838362ed93c246ab12aad4364548a1eee74e29d`다. I02의 실제 검증 코드는 `2e1df61`, CI39893880397이며 9838362는 검증 기록 후속 커밋이다. 기존 draft PR #3→#4→#5→#6 위에 쌓고 main 병합·운영 배포는 하지 않는다.

## 실제 변경 파일

| 파일 | 변경 |
|---|---|
| `backend/career/guide_choices.py` | 현재 문항 확인, 운영자 검토 파일 조회, 서버 가이드 선택, 재현 가능한 버전·지문·배분 결정, 재검증·재요청 처리 |
| `backend/career/writing_plans.py` | 기존 설계에 선택 snapshot/의존성 연결, 낡은 결정 차단, 지원하지 않는 계수 방식 보류, 최소·최대 분량 확인 |
| `backend/career/workflow.py` | 기존 Brief/Writer/Lock/Ready/Freeze 진입 시 현재 설계·분량 확인 |
| `backend/career/scoped_context.py` | I02 COVER_WRITE 조회에 현재 QuestionContract와 출처·보류 이유 반영 |
| `backend/career/api.py` | 기존 인증·소유권·operation을 재사용하는 v4 GET1개/POST2개 |
| `backend/career/activity.py` | 비AI 문항 확인·가이드 선택 활동 표시 |
| `.env.example` | 선택 기능 기본 OFF 및 운영자 로컬 catalog/review 경로 |
| `frontend/app/question-guide-choice.tsx` | 문항 조건 확인·가이드 선택·분량 조정·충돌 복구 UI |
| `frontend/app/writing-plan-panel.tsx` | 기존 대화/직접 편집 설계 패널에 선택 UI와 보류 이유·실제 단위 연결 |
| `frontend/app/style.css` | 기존 색상 안의 반응형 입력·선택 카드 |
| `frontend/package.json`, `frontend/package-lock.json` | 실제 React DOM 검사와 개발 전용 jsdom29.0.1. production 의존성 변경 없음 |
| `frontend/tests/guide-choice-dom.test.cjs` | 실제 컴포넌트 선택·배분·확인·갱신·충돌·미저장 상태 검사4개 |
| `tests/test_guide_choice_workflow.py`, `tests/test_guide_choices_api.py` | 현재 문항 우선·동일 snapshot·무변경 GET·주입/소유권/409/재요청·최종 Gate·불변 이력 검사 |
| `AGENTS.md`, `IMPLEMENTATION_STATUS.json`, `docs/UNIFIED_ACCEPTANCE_TEST_MATRIX.csv`, 이 문서 | 범위·실행 결과·호환성·미완료·다음 의존성 |

## 인터페이스와 결정

기능은 `CAREER_GUIDE_SELECTION_ENABLED=0`이 기본값이다. 켠 경우 인증된 소유자만 다음 경로를 사용한다.

- `GET /api/v4/applications/{workspace}/questions/{qid}/guides`: 현재 QuestionContract/출처·선택 revision·검색 결과·catalog 상태. 읽기만 하며 provider 호출·저장·실행은 없다.
- `POST .../contract`: 직접 확인 checkbox, 현재 revision, 계수 기준·최소·최대·필수 요구·제외 주제·출처 메모. 최대 분량은 현재 등록 문항과 일치해야 한다.
- `POST .../guide-choice`: 현재 revision/request_key와 가이드 ID·버전·내용 지문 또는 fallback, 선택적 문단 배분만 받는다. 가이드 본문·배포 권한·승인 flag를 받지 않는다.

POST는 기존 workspace 직렬 operation과 `Idempotency-Key`를 사용한다. 같은 키·본문의 재전송은 최초 결정을 돌려주고 다른 본문은 거부한다. 오래된 revision·서버 후보에 없는 버전·지문·분량은 409이며 Artifact/Source/PromptRun의 부분 저장이 없다. 실패 ExecutionRun 감사 기록은 남을 수 있다.

현재 등록 문항이 원문·상한·회사·직무의 기준이다. 확인 자료는 기존 Artifact/Source에 REFERENCE로 저장하고 `USER_CONFIRMED_NOT_LIVE_VERIFIED`를 명시한다. 운영자 검토와 사용자 선택은 지원자 Fact/Claim 승인이 아니다. 별도 Truth DB나 모델·migration을 만들지 않는다.

가이드 catalog와 release ledger는 서버의 `CAREER_GUIDE_CATALOG_DIR`, `CAREER_GUIDE_RELEASES_PATH` 로컬 파일만 읽는다. I01의 권리·scope·검토·버전 조건으로 걸러지고 실패하면 경로/원문을 노출하지 않고 fallback을 제시한다. 현재 회사의 공식 문항인 것처럼 다른 회사 사례를 표시하지 않는다. 확인하지 않은 계수 규칙은 UNKNOWN을 유지한다. 예시 전문·인용은 Writer에 넣지 않는다. 이번 구현으로 실제 corpus가 추가되거나 원문 배포 권리가 부여된 것은 아니다.

선택 결과와 현재 문항을 결합한 snapshot이 화면/QuestionBrief 입력/Writer에 동일한 hash로 전달된다. 문단 예산은 구성 수와 현재 최소·최대 범위 안에서만 저장한다. 선택한 가이드의 검토 fingerprint·버전·내용 또는 문항이 바뀌면 실행을 보류하고 관련 WritingPlan/Brief/Draft/Review를 다시 확인한다. 무관한 새 가이드 추가는 기존 선택을 낡게 만들지 않는다. 선택 기능을 끄더라도 이미 저장된 결정의 현재성 검사는 유지한다.

## 호환성과 한계

기존 `guide_for`의 exact/fallback 동작과 선택 이력이 없는 legacy Brief 호환성을 보존한다. Fact/Evidence/Claim Test/QuestionPortfolio/Review/Lock/Freeze/Submission의 기존 승인 규칙을 제거하지 않는다. Frozen 원본은 수정하지 않으며 현재 source를 취소하면 새 작성·최종 잠금·제출 준비·Freeze에서 차단한다. Claim Test 미통과를 가이드 선택으로 통과시키지 않는다.

명시한 BYTES나 공백/줄바꿈/제목 제외 방식은 기존 글자 수 검사로 정확히 검증할 수 없다. 기준과 가이드는 저장하되 자동 설계·작성·잠금을 보류한다. UNKNOWN은 미확인 안내와 기존 글자 수 검사를 유지한다. 지원하는 CHARACTERS 기준에는 확인한 최소·최대를 작성/잠금/준비에서 검사한다. 다른 계수기 구현 완료로 보고하지 않는다.

UI는 조건을 편집하면 확인 저장 전 가이드 선택을 막고, 충돌/외부 갱신 시 미저장 입력을 보존한다. 자동 재시도 대신 명시적으로 버리고 최신 기준을 읽을 수 있다. 기존 전역 미저장 이동 보호와 연동한다.

## 실행한 검증

- 로컬 관련 Python **86 passed**: guide_choice workflow/API, 기존 writing_plans/API/workflow, guide_publication, scoped_context. 실제 무료/유료 AI 호출0, 합성 자료만 사용.
- 프런트 기존30 + 새 React DOM4 = **34 passed**. 선택 후 배분 복원, 직접 확인 전 차단, 409/외부 갱신 시 입력 보존, 잘못된 총량 차단 포함.
- 전체 Ruff, 전체 Pyright(오류0), frontend lint/typecheck/production build 통과. production dependency audit0. 개발 전용 high5 advisory는 이전 단계의 잔여 사항이며 production 감사와 구분한다.
- 실제 브라우저 시각 검수 **NOT_RUN**: Work 설정에서 local browser가 비활성화되어 도구가 차단했다. 설정을 변경하거나 다른 자동화로 우회하지 않았다. DOM 상호작용 검사는 브라우저 레이아웃 검수의 대체 완료 표기가 아니다.
- 전체 Linux CI·실제 PostgreSQL·MCP·migration·privacy 결과는 아래 후속 검증 기록에 고정 SHA와 함께 기록한다. 로컬 Windows 전체 pytest의 기존 MCP 대기 문제를 skip으로 숨기지 않는다.

AC-020~025는 위 합성 자동화 범위에서 PASS다. I00~I03 25 PASS, I04 이후28 NOT_RUN. 전체 통합 서비스 인수가 끝난 것은 아니다.

### 전체 CI 최종 결과

검증한 코드·검사는 `93f58c0ab80fd15a264df135ae4d129650244c40`이며 [PR #7](https://github.com/yoon-chan-hyeok/career-harness/pull/7)의 [CI39897932162](https://github.com/yoon-chan-hyeok/career-harness/actions/runs/39897932162)는 backend/frontend 모두 SUCCESS다.

- 전체 Python **957 passed, 9 skipped**. skipped는 PostgreSQL 전용 검사이며 별도 실제 PostgreSQL 실행에서 **9 passed**다. MCP protocol과 migration 검사도 포함한다.
- Alembic upgrade/check/downgrade/upgrade 성공, 새 migration 없음. 전체 Ruff/Pyright/privacy 통과.
- frontend **34 passed**(auth11/deploy4/upgrades19), lint/typecheck/production build 성공, production dependency audit0. npm 전체 설치 보고의 개발 전용 high5와 구분한다. 기존 CSS autoprefixer 경고는 남아 있으나 build는 성공했다.

이 결과를 기록하는 후속 커밋은 AGENTS/status/이 문서만 갱신한다. 코드와 검사 파일은 위 검증 SHA와 동일하며 main·기존 PR 브랜치·운영 설정은 수정하지 않았다. 브라우저 시각 인수 NOT_RUN와 실제 운영/품질 미완료는 CI 성공 후에도 그대로 남는다.

## 미완료와 다음 의존성

I04는 이 PR의 현재 QuestionContract·선택 snapshot·WritingPlan 인터페이스 위에서 Persona/소재 제안·문항 간 배분·사람의 선택을 구현해야 한다. 기존 QuestionPortfolio/Claim Test/Review를 재사용하고 별도 승인 체계를 만들지 않는다. 후속 사용자 진행 요청과 이 PR의 검증 결과를 기준으로 별도 PR에서 진행한다.

실제 운영 catalog 권리 검토/등록, 새 UI의 브라우저 시각 인수, 실제 모델 전체 작성 품질 인수와 뒤 단계 Context 실행·trace는 아직 남았다. main 병합·운영 설정 활성화·배포·개인 원문 공개는 수행하지 않았다.
