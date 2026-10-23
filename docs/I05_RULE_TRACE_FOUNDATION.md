# I05 — 규칙 후보 인덱스·출처 대조·코드 검증·실제 실행 기록

2026-10-23 사용자의 지속 진행 목표에 따라 I04 위에서 I05를 구현했다. 기반은 `codex/i04-joint-portfolio` / `76d40977672db153a5a563e86f8ebb5e4f0e127b`, 검증 코드는079a49f/CI39902127614다. 원격 main4202b86과 I04를 확인한 뒤 `codex/i05-rule-trace-foundation`으로 분기했다. 기존 draft PR #3~#8은 보존하고 main 병합·운영 배포를 하지 않는다. 전체 목표는 I05 구현만으로 완료 처리하지 않는다.

## 실제 변경 파일

| 파일 | 실제 변경 |
|---|---|
| `backend/career/rule_pilot.py` | read-only CSV 수입, 원자 계약·출처/행 지문, 개인 pilot 접근, 원문 검토/실제 코드 평가/범위 승인/중단, 현재 문서 RuleExecution과 최종 Gate 연결 |
| `backend/career/api.py` | 기존 User/auth/operation에 private v4 규칙 조회·확인·평가·승인·중단·문서 검사. ID·revision·idempotency 검증 |
| `backend/career/workflow.py` | 기존 Review에 실제 검사와 의존성 기록, final_lock/ready에서 현재성 재확인 |
| `backend/career/activity.py` | 비AI 규칙 검토·코드 검증·승인·중단·검사 활동 표시 |
| `.env.example` | pilot 기본 OFF, 단일 owner와 private index/contracts/source-root 경로 |
| `frontend/app/rule-pilot-panel.tsx` | 개인 규칙 후보/출처 구간·계약/세 번의 확인/중단 화면 |
| `frontend/app/conversation-workspace.tsx`, `frontend/app/workroom.tsx`, `frontend/app/style.css` | 대화/직접 편집 연결과 반응형 표시 |
| `frontend/package.json`, `frontend/tests/rule-pilot-dom.test.cjs` | 실제 React DOM5를 기존 검사에 추가. 새 의존성 없음 |
| `tests/test_rule_pilot.py`, `tests/test_rule_pilot_api.py` | 새22개: 수입·52/65 차단·출처/버전·실제 사례·전송 없는 GET·실행 상태·격리/주입/재요청·최종 잠금 |
| `AGENTS.md`, `IMPLEMENTATION_STATUS.json`, `docs/UNIFIED_ACCEPTANCE_TEST_MATRIX.csv`, 이 문서 | 범위·실제 결과·호환성·미완료·다음 의존성 |

## 실제 원본 확인과 개인정보 경계

사용자가 지정한 통합 ZIP의 v4 원본에서 `09_READONLY_RULE_INDEX_246.csv`를 ignored `work/i05-reference/`에 추출해 새 수입기로 실제 읽었다. CSV SHA256은 `66ac8e94c72f50d63a5f6ede5e6ac5be43869b0052a4f0512ea9d53fc0cab85d`다. 결과는 **246행·보정 후보52·미정밀화65·활성0·출처 연결 인증0**이다. CSV 원문·개인 요약·9권 자료는 공개 소스에 복사하지 않는다. 테스트의 SYN ID 246개는 별도 합성 parser 검사이며 실제 수입 증거와 구분한다.

9권 원문 인증본은 이관팩에 없다. 인덱스를 원문 전체 인증으로 취급하지 않았고, 실제 246개 중 채택/활성화한 항목은 **0개**다. 원문 ZIP의 기존 로컬 경로를 사용자에게 비동기로 요청했으며 구현은 계속했다. 실제 원문 대조·사람 승인·실서비스 소수 규칙 활성화는 아직 완료되지 않았다.

private 기능은 `CAREER_RULE_PILOT_ENABLED=1`이고 인증 actor가 서버의 `CAREER_RULE_PILOT_USER_ID`와 일치할 때만 열린다. 기본 OFF·owner 빈 값이다. 다른 사용자와 비로그인 사용자는 원문/인덱스를 읽을 수 없다. 공용 발행 경로는 없고 `global_publish=NOT_AUTHORIZED`를 유지한다.

## 계약과 실행 순서

`CAREER_RULE_INDEX_PATH`는 실제 CSV, `CAREER_RULE_CONTRACTS_PATH`는 별도 서버 계약 JSON, `CAREER_RULE_SOURCE_ROOT`는 원문 전용 절대 경로다. 클라이언트가 파일 경로나 계약 본문을 게시하지 않는다. 원문은 해당 root 내부 UTF-8 md/txt/csv의 실제 byte hash와 line span/excerpt hash로 확인하며 root 탈출·비문서 파일·초과 크기를 거부한다. 직접 DOCX/PDF 원문 인증까지 구현했다고 표시하지 않는다.

수입은 모든 ID를 DISABLED/UNVERIFIED/NOT_RUN으로 둔다. CSV가 ACTIVE를 주장해도 신뢰하지 않는다. 52 보정 후보와 65 미정밀화 항목은 계약 파일이 있어도 이 pilot의 활성화에서 제외한다. 내부 heading ID는 source-map 증거 없이 Canonical ID와 동등하다고 표시하지 않는다. 사람이 확인한 연결도 해당 개인 지원서의 `HUMAN_ATTESTED_PRIVATE`이며 전역 인증이 아니다.

계약은 rule ID/version, 출처 파일/행/지문, COVER/RESUME scope, trigger, required evidence, allowlisted action/gate, expected output, stop, exception, 실제 양성/음성 사례를 갖는다. 동작은 **수치·수행 범위·현재 글자 수 검사3종**으로 제한한다. 임의 코드/도구/글 자동 변경·승인 생략은 허용하지 않는다.

1. 원문 구간과 실행 계약을 읽고 **SourceReview**를 별도로 남긴다.
2. 서버 계약의 양성·음성 사례를 실제 기존 hard_qa로 실행해 **RuleCodeEvaluation**에 결과 코드·입력 지문·검사 코드 지문·검사 수를 기록한다. 클라이언트가 PASSED를 선언하지 않는다. `CODE_EXECUTED_NOT_LLM`이며 실제 LLM 평가나 기존20회귀 실행이 아니다.
3. 현재 출처·평가·범위를 다시 확인한 뒤 **RuleActivation**을 해당 사용자/지원서에만 ACTIVE_SCOPED로 채택한다. SourceReview나 평가만으로 자동 활성화하지 않는다.
4. 실제 소유 문서를 검수할 때 **RuleExecution**에 SELECTED → ACTION → GATE와 실제 output hash를 기록한다. precondition 실패는 ACTION을 했다고 표시하지 않는다. 실제 실행과 통과 근거가 있는 항목만 APPLIED_VERIFIED, 미발동은 SELECTED_NOT_TRIGGERED, 실패/낡은 계약은 BLOCKED_BY_POLICY다.

기존6종 `references.compile_pack`, `rulebook` 원문 절 선택, user-scoped `writing_rules`, `promotion.validate_promotion`의 실제 모델 평가/사람 승인 경로는 수정하지 않았다. 새 코드 검사 결과로 학습 규칙의 평가를 우회하거나 WritingRuleRecord를 승격하지 않는다. 기존25 Gate 명세와 새20 정적 연결 사례는 계속 NOT_RUN이다.

## API·현재성·검증 유지

- `GET /api/v4/applications/{app}/rules`: private 후보/계약/원문 구간/검토·평가·채택 상태. 조회만 하며 provider/DB mutation0. 현재 자료에서 사라진 채택 ID도 별도 표시한다.
- `POST .../rules/{source-review|evaluate|activate|retire}`: 서버 소유 ID/version과 expected revision·직접 확인만 입력한다. client status/approval/owner/source 본문은422. 기존 직렬 run_operation과 Idempotency-Key를 사용한다.
- `GET /api/v4/applications/{app}/rule-documents/{doc}`와 `POST .../rule-documents/check`: 실제 소유 문서의 현재 지문으로 검사한다. raw document나 verdict를 받지 않으며 다른 지원서 문서도 거부한다. 같은 요청 키 재전송은 새 실행/버전/하위 무효화를 중복 생성하지 않는다.

낡은 revision·출처·구간·계약·실행 코드·근거·프로필·문서 버전은 재검토가 필요하다. 코드 변경은 이전 평가를 자동 승계하지 않는다. 인덱스가 사라져도 채택 규칙을 조용히 누락하지 않고 차단한다. 출처가 없어진 규칙도 명시적으로 사용 중단할 수 있다.

Review는 실제 RuleExecution ID를 의존성으로 저장한다. 기존 P0/P1·Claim Ledger·본인 수행·문항 배분·Claim Test·검수 답변을 보존하고 final_lock/ready에서 채택 규칙의 현재 검사까지 확인한다. flag OFF도 이미 채택한 규칙의 검사 우회 수단이 아니다. 새 채택이 없는 legacy 흐름은 유지한다. 기존 Fact/Evidence/Truth/models/migrations/Frozen 구조를 수정하지 않았다.

## 실행한 검증

- 변경 전 기존 규칙·승격·runtime trace **66 passed**.
- 새 기능/기존 주요 경로 중간95, 새 최종 계약·API22 및 전체 관련 **173 passed /93.40초**. 기존 Claim Test·Review·Lock·Guide·Material 선택 포함. 실제 공급자 호출0·합성 자료만 사용.
- frontend **43 passed**(auth11/deploy4/upgrades28; 새 React DOM5), lint/typecheck/production build 성공. DOM은 세 확인 분리·미승인 차단·409 재시도 금지·낡은 버전 중단·기본 OFF 숨김을 확인했다.
- 전체 Ruff와 최종 Pyright 오류0. 실제 Linux 전체 CI·실제 PostgreSQL·MCP·migration·privacy 결과는 후속 고정 SHA 기록을 따른다.
- 최종 Python 실행: `pytest tests/test_rule_pilot.py tests/test_rule_pilot_api.py tests/test_rulebook.py tests/test_promotion_postmortem.py tests/test_runtime_trace.py tests/test_workflow.py tests/test_joint_portfolio.py tests/test_guide_choice_workflow.py tests/test_claim_test.py tests/test_review_resolution.py -q -p no:cacheprovider`. 프런트는 `test:auth`, `test:deploy`, `test:upgrades`, `lint`, `typecheck`, `build`를 실행했다.
- 실제 브라우저 시각 인수는 Work local browser 비활성화 때문에 NOT_RUN. DOM 검사를 실제 모바일/데스크톱 레이아웃 인수로 표시하지 않는다.

AC-033~037은 실제 수입/합성 자동화 범위에서 PASS다. I00~I05 37 PASS, I06 이후16 NOT_RUN. 코드검사와 원문/실제 모델/운영 인수를 구분하며 전체 I05 실서비스 활성화나 전체 목표 완료로 표시하지 않는다.

## 남은 의존성과 지속 작업

9권 원문 제공·정확한 source-map 및 원칙별 의미 대조·사람 승인·실제 private subset 활성화가 남았다. 실제 모델 글쓰기 품질, 25개 명세 Gate·20개 정적 연계 사례의 실제 실행, 브라우저 시각 인수·staging/복구/운영은 미완료다. 개인/글로벌 Rule 발행 승인을 추정하지 않는다.

전체 목표를 유지하며 다음 I06은 이 RuleExecution의 실제 event/output/gate 지문과 I04 소재/Persona·I03 WritingPlan을 문단/불릿 why·국소 수정에 연결한다. 실행되지 않은 규칙은 NOT_AVAILABLE/REFERENCE_ONLY로 표시해야 한다. I07 동적 실행·I08 실제 인수까지 별도 PR 순서를 유지하고 main 병합·운영 자동 배포는 계속 금지한다.
