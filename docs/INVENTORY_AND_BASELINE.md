# I00 — 통합 구현 인벤토리와 기준선

이 보고서는 2026-10-22 통합 handoff를 기준으로 기존 코드와 입력 자료를 조사한 기록이다. C/v4는 Career Harness 전체 설계이고 v4.1은 그 안의 Question Guide RAG 하위 기능이다. 이번 착수 범위는 **I00·I01**이다. 자료에 적힌 설계·과거 검증을 현재 실행 성공으로 승격하지 않는다.

## 1. 기준 커밋과 기존 작업 보존

| 대상 | 확인한 기준 | 처리 |
|---|---|---|
| 기존 main | `4202b86c079df28642e24e01d420664600bad316` | I00의 기준. main 직접 수정·병합·운영 자동 배포 없음 |
| 기존 v3 브랜치 | `codex/v3-experience-shadow`, `9941043316e80db74c69026193b576fa9a916957` | PR #1과 원본 브랜치 보존. 통합 순서의 **I02 후보**로 보류 |
| 기존 v4.1 브랜치 | `codex/v41-guide-retrieval`, `26d89a92f92d7c464928afd058ab84aeea09ccda` | PR #2 이력 보존. 가이드 모듈·검사를 새 I01에서 재사용하고 대체 관계를 안내 |
| 새 I00 브랜치·PR·HEAD | `codex/i00-unified-inventory` (SHA/PR은 Git 이력 참조) | 문서·인벤토리 단위, main 기준으로 분리 |
| 새 I01 브랜치·PR·HEAD | `codex/i01-unified-guide` (다음 PR) | I00 뒤에 가이드 변경만 연결. v3 실행·미리보기 API를 함께 가져오지 않음 |

기존 `26d89a9`는 v3 변경 2개 위에 가이드 변경 1개를 쌓은 상태였다. 통합 순서는 I01 다음에 I02이므로, 기존 브랜치를 초기화하거나 덮어쓰지 않고 새 PR 계열에서 범위를 분리한다. 이전 코드가 같은 저장소에 있다는 사실은 통합 단계의 완료를 의미하지 않는다.

이 조사에서 `4202b86..26d89a9`의 기존 작성 모듈·모델·마이그레이션은 변경되지 않았다. 기존 `api.py`에는 v3 조회 경로가 추가돼 있으므로 가이드 전용 I01 재사용 대상에서 제외한다.

## 2. 실제 입력 자료와 출처 상태

통합 팩 `Career_Harness_CODEX_MASTER_HANDOFF_20261022.zip` SHA256:

`ff8d99952ddf14c484c319d842077f62435c11421fcb42cf6ef451464242ec3b`

읽은 순서는 `00_CODEX_START_HERE.md → 01_MASTER_IMPLEMENTATION_SPEC.md → 02_PHASED_PR_TASKS.md → 03_ACCEPTANCE_TEST_MATRIX.csv`다. 상위 manifest가 열거한 **9개 파일의 바이트 수·SHA256이 모두 일치**했다. 원본 첨부·예시 전문·9권 인덱스 내용은 공개 저장소에 복사하지 않는다.

| 입력 | 실제 수량·검증 결과 | 권리·사용 범위 |
|---|---|---|
| 저장소 `backend/career/assets/writing_guides/posco_dx_technical.json` | 가이드 1건 | 현재 외부 원문 실검증 없음, 명시적 공개 재배포 허락 확인 안 됨 |
| mini-kit `example-data.json` | 위와 같은 가이드 1건의 UI/생성 입력 표현 | 별도 신규 가이드로 세지 않음 |
| mini-kit 기타 파일 | `draft-screen.html`, `service-integration.md` | 참고 구현 자료. 추가 문항 코퍼스가 아님 |
| 전체 고유 가이드 | **1건**, `luxent:L2304-Q02:600:v1` | `RIGHTS_PENDING`을 보수적 기본값으로 유지 |
| 877개 문항 DB | 제공되지 않음 | 임의로 만들거나 검색·품질 검증 완료로 표시하지 않음 |
| C 감사 후보 대장 | 10행: 미승인 4개·미정밀화 보존 6개 | 모두 승인 NO, runtime NOT_RUN, release DISABLED |
| 새 팩의 v4 read-only rule index | **246행** 실제 존재 | 246개 모두 DISABLED / NOT_ATTESTED / NOT_RUN / NOT_AUTHORIZED |
| 52개 보정 후보·65개 미정밀화 표시 | 인덱스에서 실제 집계와 일치 | 서로 다른 상태 축. 전체 활성화 범위가 아님 |
| 9권 전체 원문 | 이 팩에 없음 | 인덱스·감사 요약을 전체 원문 인증본으로 취급하지 않음 |

### mini-kit과 저장소의 비교

| 비교 | 결과 |
|---|---|
| 회사·직무·문항·필수 요구·길이 메타데이터 | `selection_metadata` 완전히 동일 |
| UI 가이드 | `mini.ui.visible_writing_guide == repo.guide` |
| 생성 입력 가이드 | `mini.generation_context.visible_writing_guide == repo.guide` |
| 작성 규칙 | 양쪽 5개 모두 동일 |
| 권장 내용 배분 | 양쪽 `70/120/280/130` |
| 예시 내용·버전 | 동일, 592자·본문 2문단. 전문은 이 보고서에 싣지 않음 |
| 원문 URL·문단 해시 | 동일 |
| 계수 정책 | 양쪽 `counting_basis=not_stated`; 공식 계산 기준 확인 완료가 아님 |

raw JSON 파일 해시는 wrapper 차이 때문에 다르다. mini-kit은 `schema_version/ui/generation_context/generation_gate`, 저장소는 `guide/rules/provenance/source_verified_live` 포장을 사용한다. 가이드 자체의 내용 차이는 없다.

- mini-kit JSON SHA256: `2c4e979eaa12c5230c05e6f5ac3899b35d316380de43155c5189329ca6a6e337`
- 저장소 JSON SHA256: `8df1e20f3040c9b23e65f9f6fe7939f19ab014e8ce392d1e3baea358b08902f7`
- 공통 canonical guide SHA256: `7cd258e6c9e13eb3469dddde8cd39883affc43267a5c29975d7fa1bce8fa3246`

canonical 범위는 guide 객체를 `ensure_ascii=False, sort_keys=True, separators=(",", ":")`로 JSON 직렬화한 UTF-8 바이트다. mini-kit의 UI·생성 입력에 선언된 두 guide hash와 실제 계산값이 일치한다. raw 파일 해시·guide 해시·향후 SourceManifest 해시를 서로 혼용하지 않는다.

`semantic_reviewed=true`는 원형 제작자의 메타데이터다. 서버 검증이나 재배포 허락이 아니다. 원형에는 `source_verified_live=false`, `use_as_applicant_fact=false`가 있고, mini-kit 자체도 `applicant_facts=null`, `ready=false`, `model_called=false`, `application_connected=false`다. mini-kit 3파일에서 별도의 라이선스·권리·허가 문구는 확인되지 않았다.

## 3. 기존 모듈과 보호할 계약

아래 시그니처는 실제 Python AST와 함수 본문으로 확인했다. I00/I01은 이 함수들을 대체하거나 승인 조건을 줄이지 않는다. 줄 번호는 브랜치에 따라 달라질 수 있어 함수명으로 연결한다.

| 현행 함수·라우트 | 확인한 동작 | 호환성 조건 |
|---|---|---|
| `writing_plans.guide_for(company: str, role: str, question: dict)` | 회사·직무·원문·600자 일치 시 `ARCHIVED_REFERENCE`, 그 외 7종 유형 구성 | 원문 배분·fallback 및 기존 호출 계약 보존 |
| `writing_plans.preview(service, workspace, qid)` / `public_preview(service, workspace, qid)` | 현재 질문·guide hash·선택 Evidence·전략·작성계획 revision 조회 | 조회에 새 AI 호출·상태 변경을 추가하지 않음. 아래 원문 권리 blocker 별도 |
| `writing_plans.persist(service, workspace, qid, request=None)` / `require_current(service, workspace, qid, brief)` | 계획 revision·guide snapshot과 연결된 기존 Brief 최신성 검증 | 새 가이드 연결은 I03. I01에서 저장 계약 변경 금지 |
| `portfolio.plan(service, workspace, manual=None)` | 모든 문항을 정확히 한 번 배분, 확인된 근거만 허용, 역할·메시지 중복 검사 | Guide 검색 결과로 기존 배분 승인 우회 금지 |
| `portfolio.approve(service, workspace)` / `require_current(service, workspace, brief)` | 다문항 Portfolio LOCKED·fresh·현재 Brief 의존성 확인 | 미승인·낡은 배분으로 Claim 승인·작성 진행 금지 |
| `experience_options.options(service, workspace, slot='strategy')` / `active_selection(service, workspace, slot, *, fallback=False)` | 소유 Evidence, 기여, 현재 fingerprint·EvidencePack 적합성 재확인 | Guide 코퍼스와 개인 경험 검색의 namespace 분리 |
| `Workflow.question_brief(self, ident, qid, manual=None)` | 기존 작성계획을 준비하고 질문 메시지·근거 설계 | 새 힌트가 사용자 Fact나 승인으로 승격되지 않음 |
| `Workflow.approve_question(self, ident, qid)` | Portfolio 최신성, ClaimEvidenceTest 통과, WritingPlan 승인 후 잠금 | 현재 Claim Test를 항상 유지 |
| `Workflow.draft(self, ident, qid, manual=None)` | 전략·Brief LOCKED, Portfolio/Claim Test/계획 최신성, 선택 경험 일치 검증 | 서버 Gate를 오프라인 검색으로 대체하지 않음 |
| `claim_test.require_pass(service, workspace, qid, brief)` | PASSED뿐 아니라 현재 brief ID·version·depends_on·fresh 확인 | 다른 버전 검사 결과 재사용 금지 |
| `review_resolution.require_resolved(service, workspace, review, document, *, locking=False)` | 현재 Review·문서·모든 필수 답변·RESOLVED 확인 | 미해결 질문이나 다른 문서 답변으로 잠금 우회 금지 |
| `artifacts.fresh(db, user, artifact, seen=None)` | 사용자·상태·출처·Fact·재귀 의존성 유효성 | 정정·오래된 결과 처리 유지, Frozen 기록 불변 |
| `Workflow.ready(self, ident)` | 모든 질문·레쥬메의 현재 본문/검수 LOCKED, Claim/Portfolio/답변/ledger/최종 판단, P0/P1 차단 | 하나라도 미완료면 준비 완료 금지 |
| `Workflow.freeze(self, ident)` | READY_TO_FREEZE 필요, `ready()` 재검사, 보관본 LOCKED와 SUBMISSION_FROZEN | Freeze는 실제 제출이 아님 |
| `Workflow.confirm_submission(self, ident, confirmed: bool)` | SUBMISSION_FROZEN + 명시 confirmed 필요, 별도 제출 확인 기록 | 자동 SUBMITTED 금지 |
| `references.compile_pack(db, user, stage: str, domain='')` / `promotion.validate_promotion(db, user, data)` | 기존 룰팩·사용자별 후보 승격 검증 | 새 246 인덱스 자동 연결·ACTIVE 전환 없음 |

기존 HTTP 접점은 `GET/POST /api/applications/{workspace}/questions/{qid}/writing-plan`과 `POST /api/applications/{workspace}/actions/{action}`이다. 후자의 실제 action 이름은 `question-portfolio`, `approve-portfolio`, `question-brief`, `claim-test`, `approve-question`, `generate`, `review`, `final-lock`, `ready`, `freeze`, **`confirm`**이다. 문서의 논리 이름 `draft`·`confirm_submission`을 신규 REST 경로로 착각해 기존 API를 바꾸지 않는다.

## 4. 기존 증분 인수 평가

| 항목 | 평가 | 재사용·보완 결정 |
|---|---|---|
| 기존 exact/fallback, WritingPlan, QuestionPortfolio, Claim Test, QA/Lock/Freeze/Submission | COMPLETE: 기존 구현 존재. 이번 실행 검증은 아래 결과 별도 | 현행 서버 함수를 그대로 유지 |
| 가이드 수입·원본 보존·해시·버전 충돌·BM25·템플릿 대체 | PARTIAL | `26d89a9`의 가이드 코드·검사를 I01에서 재사용 |
| 기존 GuideRecord/검색 DTO | PARTIAL | 통합 `SourceManifest`·`GuideCandidate`, namespace/권리/조회 방식 명시 보완 |
| legacy JSON에 개인 Source/Evidence 메타데이터 주입 차단 | PARTIAL | 허용 도메인·입력 경계를 명시하고 AC-014 회귀 추가 |
| 부정 요구·상반된 질문 처리 | PARTIAL | 오분류 시 보수적 fallback, 제외 사유 검사 보완 |
| 미확인 계수 정책의 정확 출처 매칭 | CONFLICT | 현재 정책을 아는 것처럼 표시하지 않는 `LEGACY_EXACT + UNKNOWN` 계약으로 정리. 기존 `guide_for()` 불변 |
| 순수 오프라인 조회와 실행 가능한 vector callback | CONFLICT | callback 대신 사전 계산 점수 데이터를 사용. I01에서 외부 호출 경로 없음 |
| 새 기능 기본 OFF | PARTIAL | 실제 기본 OFF 경계와 검사 추가. 기존 writing-plan은 계속 동작 |
| v3 ExperienceCard·Shadow Plan | PARTIAL / I02 후보 | 원본 PR #1 보존·보류. ContextCompiler·통합 manifest 완료로 주장하지 않음 |
| 문단 Trace·RuleExecution·Persona/Material HITL·Writer 합류 | UNVERIFIED 또는 설계 계약만 존재 | I02 이후 선행순서 준수. 이번 I01에서 구현·활성화하지 않음 |
| 실제 모델 품질·운영 staging·877건 검색 품질 | UNVERIFIED | 이번 실행 대상 아님 |

위 보완은 I01의 승인된 변경 계획이다. 실제 구현·검사 완료 상태는 I01 PR의 변경 파일과 결과로 확정한다.

## 5. 남은 원문 권리 문제 — 서비스 전체 PASS 아님

현행 `writing_plans.public_preview()`는 `_`로 시작하는 내부 필드만 제거한다. `preview()`의 `guide` 안에는 기존 `reference_example` 전문이 남으므로 **기존 writing-plan API의 원문 예시 노출에 대한 권리 검증은 해결되지 않았다**.

새 I01 오프라인 검색에서 미승인 전문을 내보내지 않는 검사와, 기존 서비스 전체의 원문 공개 권리 승인은 다른 범위다. **AC-012를 서비스 전체 PASS로 표시하지 않는다.** 현재 경로의 권리 검토·외부 응답 투영·화면/Writer snapshot 호환성은 I03의 blocker로 관리하고, 실제 연결 전에 해결해야 한다. I01은 이 문제를 감추거나 공개 사용 권한을 임의 생성하지 않는다.

## 6. 실제 실행 증거

| 실행 범위 | 명령·증거 | 결과 |
|---|---|---|
| 이번 자료 감사 | `python work/master-handoff-20261022/source_inventory_check.py <사용자 제공 통합 ZIP> .` | exit 0. manifest 9개 일치, 가이드 비교 6항목 모두 true, unique guide 1 |
| 기존 PR #2 CI | SHA `26d89a92f92d7c464928afd058ab84aeea09ccda`, [CI 39775757312](https://github.com/yoon-chan-hyeok/career-harness/actions/runs/39775757312) | 기존 기록 SUCCESS. 이번 실행의 새 통과 기록과 구별 |
| 이번 전체 로컬 pytest 시도 | `pytest -vv -o faulthandler_timeout=45` | Windows MCP stdio 대기에서 중단. 완료·PASS 아님 |
| 이번 핵심 기존 계약 회귀 | `pytest tests/test_writing_plans.py tests/test_writing_plans_api.py tests/test_rulebook.py tests/test_portfolio_plan.py tests/test_portfolio_review.py tests/test_claim_test.py tests/test_review_resolution.py tests/test_workflow.py -vv -p no:cacheprovider -o faulthandler_timeout=45` | **106 passed / 314.45초**, 변경 전 SHA26d89a9, 격리 SQLite·모델 호출 없음 |
| 새 I01 검사·전체 회귀·원격 CI | I01 PR에서 확정 | I00 시점 NOT_RUN |
| 변경 전 정적·개인정보 검사 | `ruff check .`, `pyright --pythonpath <venv-python>`, `python scripts/check_privacy.py` | 전부 exit 0. 새 프런트·마이그레이션 검사는 I00 CI에서 확인 |

원본 acceptance CSV는 53개 항목이 모두 NOT_RUN으로 제공됐다. 이번 I00/I01의 실행 증거와 연결해 상태를 갱신하고, I02~I08을 기존 테스트나 스키마 존재만으로 PASS로 바꾸지 않는다. 실제 모델·운영·외부 사이트 권리는 이번 검사 결과에 포함하지 않는다.

## 7. 범위와 다음 의존성

- I00: 인벤토리·기준선·통합 순서와 보고 계약. 제품·DB·운영 설정 변화 없음.
- I01: 독립 가이드 수입·오프라인 후보 검색·권리/namespace/원문 경계·회귀. 사용자 Truth 조회·새 API/UI·LLM·PromptRun·Rule 활성화·마이그레이션 제외.
- I02: I01 수용 후 현재 Truth를 참조하는 Context/Experience projection·manifest·read-only Shadow 계약. 기존 v3 후보를 여기서 통합 평가한다.
- I03: I02 계약 확정과 기존 원문 권리 blocker 해결 후, Guide 선택·WritingPlan·동일 snapshot 연결. I04 이후는 통합 계획의 선행조건을 따른다.

기존 브랜치는 보존하고 공유 커밋을 강제로 덮어쓰지 않는다. 새 기능을 OFF로 돌리거나 해당 증분 커밋을 revert하는 경로를 사용한다. main merge와 운영 배포는 수행하지 않는다.

## 8. I00 원격 기준선 후속 결과 (2026-10-23)

[I00 PR #3](https://github.com/yoon-chan-hyeok/career-harness/pull/3), head d4e1689, [CI39888623254](https://github.com/yoon-chan-hyeok/career-harness/actions/runs/39888623254): backend 전체 검사·실제 PG·migration·privacy 성공. frontend는 기존 Next.js15.5.27의 production 의존성 보안 검사 실패로 이후 lint/types/tests/build SKIPPED다. 전체 CI PASS가 아니며 I01 보고서의 기존 의존성 blocker를 먼저 해결해야 한다.
