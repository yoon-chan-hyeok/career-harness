# I04 — 본인 근거와 가이드의 문항 배분·Persona 선택

2026-10-23 사용자 후속 진행 요청에 따라 I04만 구현한다. 기반은 `codex/i03-guide-writing-plan` / `460150b1ddbeaf3fbbacbb3961260f73d5608eab`다. I03 검증 코드는93f58c0, CI39897932162 backend957/별도PG9/frontend34 성공이며 460150b는 문서 후속 커밋이다. 원격 main4202b86·I03 브랜치를 확인한 뒤 `codex/i04-joint-portfolio`를 분기했다. 기존 PR #3~#7은 draft/unmerged로 보존하고 main 병합·운영 배포는 하지 않는다.

## 실제 변경 파일

| 파일 | 변경 |
|---|---|
| `backend/career/joint_portfolio.py` | 현재 가이드와 본인 근거의 조회·AI/직접 작성표 제안·명시 선택, PersonaDecision/MaterialDecision 버전과 재검증 |
| `backend/career/portfolio.py` | 기존 plan/approve/require_current 재사용, 새 선택 반영·별도 승인, legacy 경로로 우회 방지 |
| `backend/career/workflow.py` | 기존 전략 승인에 Persona 확인 연결, Brief에서 선택 소재·메시지 그대로 사용, 최종 잠금의 현재 배분 확인 |
| `backend/career/writing_plans.py` | 화면/Brief/Writer의 동일 소재·Persona snapshot과 의존성, 선택 근거 표시, 현재성·승인 보류 |
| `backend/career/api.py` | 기존 인증·operation·동의·예산 경계를 재사용하는 v4 GET1/POST2 |
| `backend/career/prompts.py`, `backend/career/references.py`, `backend/career/activity.py` | bounded joint_portfolio 역할·기존6종 strategy 지침·실제 trace/활동명 |
| `.env.example` | CAREER_JOINT_PORTFOLIO_ENABLED=0 |
| `frontend/app/joint-portfolio-panel.tsx` | 모든 문항의 역할/메시지/수행/수치/핵심 장면 편집, Persona 선택·수정·혼합·직접 작성·거절·보류, 두 승인 |
| `frontend/app/conversation-workspace.tsx`, `frontend/app/workroom.tsx`, `frontend/app/style.css` | 대화/직접 편집에 같은 패널·미저장 보호·반응형 배치 |
| `frontend/package.json`, `frontend/tests/joint-portfolio-dom.test.cjs` | 기존 CI 명령에 실제 React DOM 검사4개 추가. 새 패키지/production 의존성 없음 |
| `tests/test_joint_portfolio.py`, `tests/test_joint_portfolio_api.py` |30개 합성 계약·워크플로·실제 HTTP 검사 |
| `AGENTS.md`, `IMPLEMENTATION_STATUS.json`, `docs/UNIFIED_ACCEPTANCE_TEST_MATRIX.csv`, 이 문서 | 실제 결과·호환성·미완료·다음 의존성 |

## 사용 흐름과 인터페이스

`CAREER_JOINT_PORTFOLIO_ENABLED=0`이 기본값이다. 인증·소유권·기존 서비스 동의를 통과한 사용자의 현재 지원서에서만 다음을 제공한다.

- `GET /api/v4/applications/{workspace}/portfolio`: 문항/가이드 지문·현재 직무 근거 매핑·Direct/Adjacent/No Evidence·HOLD 이유·기존 경험 선택·제안/결정 버전·현재 승인 상태. DB 변경/provider 호출0이며 `can_execute=false`다.
- `POST .../portfolio/propose`: 현재 input_revision, use_ai, max_input_tokens. 기본 use_ai=false는 명확히 표시된 **직접 편집용 작성표**다. 안내 문구를 실제 초안/사실로 생성했다고 표시하지 않는다. AI 요청은 명시한 `external_transfer_confirmed=true`와 기존 서버 동의/AI 사용량 예산이 필요하다.
- `POST .../portfolio/decide`: proposal ID/version, expected decision revision, ACCEPT/MODIFY/COMBINE/DIRECT/REJECT/HOLD와 후보 ID·직접 표현·모든 문항의 소재. 임의 가이드 본문·소유자·승인 flag를 허용하지 않는다.

POST는 기존 run_operation의 workspace 직렬 실행·실패 rollback을 사용하며 `Idempotency-Key`가 필수다. 동일 키·본문은 최초 결과, 다른 본문은409다. 낡은 문항/가이드/수행/출처/전략/매핑/선택/선호 기준이나 조작한 ID는409이며 부분 Artifact/Source/PromptRun 저장이 없다. 실패 ExecutionRun 감사는 남을 수 있다. 실제 AI가 호출된 후 검증 실패했다면 실제 호출 trace와 사용량은 기존 감사 규칙을 따른다.

현재 모든 문항을 정확히 한 번 배분해야 선택을 저장한다. 같은 프로젝트를 여러 문항에 쓸 수 있으나 정규화한 역할·메시지·핵심 장면과 프로젝트 안의 근거 역할, 같은 metric ID 반복은 수정해야 한다. 수치는 선택한 본인 근거에 연결된 현재 MetricRecord만 고른다. 수행 범위 미확인/철회/표현 자료/NO_EVIDENCE는 HOLD다. 사용자가 이미 선택한 경험은 조용히 다른 것으로 바꾸지 않는다.

Persona·소재는 별도 application-scoped Artifact 결정이다. 인증 사용자·제안 ID/버전·선택/미선택/거절 근거·요청 키·작성시각(기존 Artifact 열)을 기록한다. 변경은 새 버전으로 남긴다. Persona 표현·사용자 초안·선호는 Fact 승인이 아니며 `claim_approval_granted=false`다. Voice/선호는 기존 user-scoped 읽기 계약을 재사용하고 별도 프로필 DB나 편집 체계를 만들지 않았다.

선택 저장은 PersonaDecision을 ACTIVE로 남기고 기존 QuestionPortfolio를 ACTIVE로 구성한다. **전략과 함께 Persona를 다시 승인 → 모든 문항 배분을 별도로 승인**해야 Brief/작성에 들어간다. Persona가 기존 ApplicationBrief의 사실·직업 정체성을 자동 덮어쓰지 않는다. 의미를 바꾸려면 기존 전략을 수정·재승인하고 새 기준으로 다시 제안/선택해야 한다. REJECT/HOLD는 선택·승인으로 표시하지 않고 이유를 남기며 작성 경로를 막는다.

현재 선택 snapshot이 WritingPlan 화면·QuestionBrief 입력·Writer에 동일하게 들어간다. Brief가 선택한 근거나 주 메시지를 임의 대체하면 거부한다. 이후 ClaimEvidenceTest·문항 승인·문서 Ledger·Review·전체 검수·최종 잠금·ready/freeze/실제 제출 확인은 그대로다.

## Context·권리·무효화·호환성

AI 제안은 I02의 QUESTION_PORTFOLIO ContextPack에서 현재 지원의 사용 가능한 본인 근거·연결 Truth·범위에 맞는 명시 선호를 읽는다. 가이드는 I03 snapshot에서 의도·필수 요구·전이 한계·배분·제한만 투영해 보내며 예시 전문/구조 예문도 해당 프롬프트에서 제외한다. 개인 Fact를 글로벌 Guide 검색에 넣지 않는다. 필수 근거를 임의 절단하지 않고 20개 범위나 전체 입력 예산을 넘으면 보류한다.

I02 compiler 자체의 `external_transfer_allowed=false`/read-only 표기는 권한으로 재해석하지 않는다. compiler는 순수 조회이며 전송 여부를 결정하지 않는다. 전송은 새 POST의 명시 확인, 기존 User 동의 경계와 run_operation 사용량 예약 뒤에만 수행한다. 저장 manifest는 원래 preview 계약과 출처 지문을 보존한다. 신규 AI 역할도 기존6종 strategy 지침과 실제 provider 정책을 사용한다. 새 Rule 활성화나 I05 실행 증거를 만들지 않았다.

현재 지원서의 소재·Persona 또는 공동 배분 버전이 바뀌면 이를 공유하는 현재 QuestionPortfolio/WritingPlan/Brief/Claim Test/Draft/Review를 재확인한다. 공동 배분에 종속된 문항들은 같은 지원서에서 함께 무효화될 수 있다. 별도 지원서의 독립 산출물·Fact·과거 SubmissionBundle 원본은 바꾸지 않는다. 가이드/수행 범위/출처/선호 변경도 실행 시 fingerprint로 다시 확인한다.

새 결정 이력이 없는 legacy exact/fallback·전략·문항 배분은 기존 흐름을 유지한다. 기능 OFF는 새 API/UI 진입을 막지만 저장된 선택을 legacy 경로로 우회하도록 허용하지 않는다. 해당 사용자는 기능을 다시 켜 현재 선택을 확인해야 한다. 롤백은 미채택 pilot에서는 flag OFF, 채택 후에는 검증을 보존하는 수정/되돌림 PR로 진행한다. DB 모델·Truth 저장소·migration·Frozen 구조는 변경하지 않았다.

## 실행한 검증과 한계

- 관련 Python131개 통과 후, 마지막 metadata/표시 보완의 새 I04 계약·API30개 재통과. 원안/혼합/수정 분기와 하위 snapshot 갱신 추가 확인1개 통과. 합성 자료·Fake provider만 사용했으며 실제 외부 AI 호출0이다.
- frontend38개(기존34+새 실제 React DOM4), lint/typecheck/production build 통과. DOM 검사는 ID 선택·미확인 수행 차단·분리 승인·HOLD·409/외부 갱신 시 입력 보존을 확인한다. 새 의존성 없음.
- 전체 Ruff·Pyright 오류0. 고정 코드 SHA의 Linux 전체 CI·실제 PostgreSQL·MCP·migration·privacy 결과는 후속 절에 기록한다.
- 실제 브라우저 시각 검수는 **NOT_RUN**이다. 이전 단계에서 Work의 local browser 비활성화를 확인했으며 우회하거나 켜지 않았다. DOM 검사가 실제 모바일/데스크톱 레이아웃 인수 완료를 뜻하지 않는다.
- 중복 검사는 정규화한 동일 문자열·같은 수치 ID 중심이다. 의미가 비슷한 다른 표현이나 서로 다른 ID의 동등 수치에 대한 완전한 의미 중복 판정은 구현하지 않았으며 `semantic_distinctness=NOT_VERIFIED_BY_STRING_CHECKS`다. 기존 전체 PortfolioReview와 사람의 확인을 생략하지 않는다.
- 실제 AI 제안/최종 글 품질·실제 corpus 권리 승인·운영 인수는 미완료다. 오프라인 작성표는 생성 품질 증거가 아니다. 자동 Rule 적용·단위별 trace·동적 전체 runtime을 구현했다고 표시하지 않는다.

AC-026~032는 위 합성 자동화 범위에서 PASS다. I00~I04 32 PASS, I05 이후21 NOT_RUN. 전체 제품·운영 완료 표기가 아니다.

## 다음 의존성

I05는 현재 결정 ID/version·Context manifest와 기존6종 지침을 보존하면서 Rule 후보의 읽기 전용 인덱스·검증된 소수 실행 계약·실제 trace 기반을 별도 PR로 추가해야 한다. 52/65개를 자동 활성화하지 않는다. I06 Writer 설명/문단 단위 trace는 이 I04의 사용자 선택과 I05의 실제 실행 증거에 의존한다. 이번에는 I05 이후·main 병합·운영 배포를 수행하지 않았다.
