# Career Harness 통합 구현 계획 — C/v4 상위 설계와 v4.1 하위 기능

이 저장소는 하나의 Career Harness다. **C/v4가 전체 제품·개인 Context·HITL·Rule·Trace 아키텍처를 정하고, v4.1은 그 안의 Question Guide RAG를 정의한다.** 별도 애플리케이션·별도 사용자 Truth 저장소·독립 Workflow 엔진으로 분리하지 않는다.

2026-10-22 사용자가 통합 handoff를 구현 기준으로 지정했다. 이번 초기 범위는 **I00·I01만**이다. 아래 I02~I08은 의존성과 인터페이스를 기록한 향후 계획이며 구현·실행·배포 승인이나 완료 기록이 아니다.

## 1. 통제 기준과 원본 지문

| 자료 | SHA256 |
|---|---|
| 통합 handoff ZIP | `ff8d99952ddf14c484c319d842077f62435c11421fcb42cf6ef451464242ec3b` |
| `00_CODEX_START_HERE.md` | `1caa26a9f69f04b12f5cae6744dcdcd7158f12e15bed50ece520da260291adcc` |
| `01_MASTER_IMPLEMENTATION_SPEC.md` | `27da877fa7e993c086dfd82dcc6e94488834555b313348feb92bcec8af21897e` |
| `02_PHASED_PR_TASKS.md` | `1d72c08de7cae60ca798f0c3dd1dc1255b682605a64a4d1bc09a02bea365a788` |
| `03_ACCEPTANCE_TEST_MATRIX.csv` | `a4a774873b13627d4ceb2222ff5bfb66bc205180691d321ec71bb99d730aab30` |

우선순위는 사용자 최신 요청과 서버 안전 불변식 → 통합 MASTER/단계별 작업서 → v4.1의 Guide 상세 계약 → v4 전체 설계 → 원본 참고 자료다. 참고 문서의 '구현됨'·검토 표시·원칙 ID 수는 실행 완료 증거가 아니다. 원본 첨부·개인 Rulebook·246 인덱스 전문은 공개 저장소로 복사하지 않는다.

검토한 기존 main은 `4202b86c079df28642e24e01d420664600bad316`이다. 매 PR 착수 시 실제 원격 HEAD와 변경 파일을 다시 확인한다. 기존 가이드 증분 `26d89a9`는 재사용하고, v3의 `9941043`은 I02 후보로 보관한다. 새 I00은 main 기준, I01은 I00 위에서 가이드 관련 변경만 담는다. 원래 브랜치·PR의 이력은 보존하며 대체 관계를 명시한다.

## 2. 단일 PR 순서

| 단계 | 범위 | 선행조건·완료 증거 |
|---|---|---|
| **I00** | 실제 코드·자료·권리·기준선·기존 작업 인수 | SHA pin, unique guide 1건, 기존 검사 실행 결과와 실패/중단/skip 구별 |
| **I01** | Guide importer·오프라인 검색·구조 적합성·fallback | I00 기준선. 기존 exact/7종 fallback 보존, 개인 namespace·미허가 전문·부정 요구 차단. API/UI 불변 |
| I02 | 사용자별 Context manifest·Experience projection·read-only Shadow | I01 수용. Truth 중복 저장 없이 참조, 소유권·버전·scope·budget·consent, preview 부작용 0 |
| I03 | QuestionContract·Guide 선택·WritingPlan 연결·최소 선택 화면 | I02 인터페이스. 기존 원문 권리 blocker 해결, 화면/Brief/Writer 같은 snapshot, stale 선택 충돌 |
| I04 | Guide + 개인 Evidence의 다문항 배분·Persona/소재 HITL | I03의 검증된 GuideMatch + I02 Context. 문항 간 배분과 문항 내부 구조의 별도 승인 |
| I05 | Rule read-only index·승인된 소수 Rule 계약·Trace 기반 | 출처/Canonical ID map 검증, 실제 승인·평가·scope 증명. 미승인 52개·미정밀화 65개 비활성 |
| I06 | Traceable Writer·Resume·문단/불릿 Why·국소 수정 | I04 선택·I05 실제 실행 기록. 기존 Claim Test/Review/Lock/ready/freeze Adapter 사용 |
| I07 | 동적 실행·재개·Resume/Interview/Outcome 연결 | 앞선 계약과 검증된 실행 Adapter. legacy 명령 유지, 필수 Gate 생략을 완료로 취급하지 않음 |
| I08 | 실제 모델 기능 인수·권리·운영 staging·롤백 | 고정 SHA의 CI, 실제 입력/출력·공급자/프롬프트·사람 검토·운영 복구 증거. 배포는 별도 요청 |

v4 원문의 Context 우선 계획과 v4.1 G0/G1 선행은 충돌하지 않도록 위 순서로 통합한다. I01의 독립 검색은 Context 실행에 의존하지 않지만, I03 이상의 저장·HITL·Writer 연결은 I02 계약 없이 중복 설계하지 않는다. 기존 사용자가 제외한 성능 비교 실험은 다시 출시 의무로 넣지 않으며, 기능 정확성·안전·운영 인수는 계속 검증한다.

## 3. 데이터와 인터페이스 경계

### I01: 지금 고정할 경계

- `SourceManifest`: source ref, 원본 payload hash, namespace, 원문/파생 분석 구분, 사용·공개 권리, 검토 상태와 버전. 개인 Source/Evidence를 공용 Guide 입력으로 허용하지 않는다.
- `GuideCandidate`: guide ID/version/hash, 현재 문항 참조, `EXACT/ADVISORY_ANALOGY/FALLBACK_TEMPLATE/REJECTED`, `retrieval_mode`, 채택되지 않은 후보 상태, coverage/missing/conflicts, 실제 제한, 출처·권리·배제 사유.
- `LEGACY_EXACT`는 같은 회사·직무·원문·600자에 대한 기존 출처 매칭을 보존하는 전략이다. `counting_basis=not_stated`는 UNKNOWN으로 남기며 공식 계수 정책 검증 완료로 표시하지 않는다.
- 가이드 내부 기능·글자 배분은 구조적 힌트다. 다른 회사·다른 자수에서는 현 문항을 우선하고 새 제안으로 표시한다. 예시 프로젝트·수치·회사 사실을 개인 Claim으로 이식하지 않는다.
- I01은 순수 오프라인 계산만 사용한다. 선택형 의미 점수는 실행 callback이 아닌 사전 계산 데이터로 전달한다. 없거나 부적합하면 LEXICAL_ONLY/fallback이며 의미 검색 실행을 주장하지 않는다.
- 새 기능은 기본 OFF이고, 제품 API/화면에는 아직 연결하지 않는다. 새 I01 기능을 끄더라도 기존 `guide_for`와 작성 흐름은 계속 작동한다.

### I02 이후: 이 계약을 먼저 맞춘 뒤 연결

```text
authenticated actor + task type + application/question/experience scope
  + required evidence IDs + approved rule version + token budget + consent
  → ScopedContextManifest / task ContextPack

current QuestionContract
  + global GuideCandidate (advice only)
  + user-owned EvidenceCandidates (fact candidates only)
  + scoped approved rules
  → joint portfolio proposal
  → explicit user decisions
  → per-question WritingHint / existing WritingPlan
  → existing QuestionBrief / ClaimEvidenceTest / approval / draft / Review
  → provenance and actual execution trace
```

인증 사용자 ID는 서버가 결정한다. 사용자 Truth와 글로벌 Guide는 검색 코퍼스·인덱스·권위·Provenance가 분리된다. 기존 Artifact의 사용자/지원/slot/version/depends_on/source_ids를 우선 재사용하며 새 테이블은 꼭 필요한 경우에만 별도 additive migration과 rollback 검사로 도입한다.

`QuestionPortfolio`는 지원서 전체 문항의 역할·소재·메시지·수치 배분, `WritingHintPlan`은 개별 문항 내부 기능·분량 설계다. 승인 이벤트·버전·무효화 범위를 공유하지 않는다. Persona/소재/Claim은 후보와 사용자 선택을 구분한다.

선택 저장은 서버가 소유권을 확인한 ID/version과 expected revision·idempotency key를 사용한다. 클라이언트가 Guide 원문·사용자 ID·Rule 상태·승인 여부를 주입할 수 없다. 변경은 필요한 최신 Plan/Brief/Claim Test/Draft/Review만 stale로 만들고 무관한 Fact·다른 문항·과거 SubmissionBundle은 보존한다.

새 API는 I03 이후 기존 `api.py`의 인증·사용량·동의·operation wrapper를 재사용하는 명시 경로로 추가한다. 현행 writing-plan GET/POST와 actions API를 덮어쓰지 않는다. GET preview는 모델 호출·DB 상태 변경 0, 외부 모델 제안은 명시 POST와 동의·예산 검사를 거친다. MASTER의 `/api/v4/...` 경로는 향후 인터페이스 방향이며 현재 구현된 경로 목록이 아니다.

## 4. 약화할 수 없는 기존 검사

1. Fact·Evidence·Source·Ownership·Metric·ClaimBoundary와 사용자 소유권이 진실 기준이다. 표현 자료·가이드·선호·모델 응답이 이를 덮지 않는다.
2. 현재 질문과 필수 요구·한도는 과거 Guide보다 우선한다. 미확인 계수 정책은 확인 필요로 남긴다.
3. 다문항 `QuestionPortfolio` 승인과 현재 의존성을 유지한다. Guide 검색이 승인·잠금·제출 이벤트를 발생시키지 않는다.
4. ClaimEvidenceTest의 현재 Brief ID/version·depends_on·PASSED 확인을 `approve_question`, `draft`, `ready`에서 계속 사용한다.
5. Review P0/P1, 미해결 질문, invalid source, 요구된 근거 공백의 차단을 유지한다. 본문과 검수·답변의 버전 일치를 검증한다.
6. 모든 요청 문서가 현재 상태로 잠기고 최종 확인을 통과해야 `ready()`·`freeze()`가 가능하다. Freeze는 SUBMISSION_FROZEN이며 실제 제출은 별도 명시 확인이다.
7. 제출 보관본은 불변이다. 이후 정정은 현재 Truth/산출물 최신성과 차이 기록에 반영한다.
8. 규칙 검색·참고·선택은 실제 적용 증거가 아니다. 실제 trigger/action/gate/output 기록이 없으면 `APPLIED_VERIFIED`를 표시하지 않는다.
9. 예산·권리·제공자 문제에서 필수 근거를 조용히 삭제하거나 허위 성공·자동 유료 전환을 만들지 않는다.

## 5. 검증 상태와 현재 blocker

`DESIGN_PRESENT`, `IMPLEMENTED_LOCAL`, `CI_PASSED`, `E2E_SYNTHETIC_PASSED`, `REAL_MODEL_EVAL_PASSED`, `STAGING_PASSED`, `PRODUCTION_ROLLED_OUT`는 별개다. 53개 acceptance 항목은 실제 명령·결과·SHA와 연결해서만 통과 처리한다. 8개 기존 합성 사례, 20개 별도 정적 Rule 사례, 실제 모델·사람 검토를 서로 대체하지 않는다.

현재 기존 `writing_plans.public_preview()`는 가이드의 예시 전문을 그대로 반환하는 경로가 있다. 새 I01의 미허가 전문 차단은 해당 오프라인 모듈 범위의 검증이며 **서비스 전체 AC-012 통과가 아니다**. I03의 외부 응답·화면/Writer snapshot 연결 전에 이 권리 문제를 해결한다. 외부 코퍼스 877건, 실제 임베딩/재판정 모델, 원본 9권 전체·전역 공개 권한은 확보됐다고 가정하지 않는다.

현재 실행 증거와 기존 작업 인수 평가는 `INVENTORY_AND_BASELINE.md`에 남긴다. 중단·실패·skip·미실행은 그대로 기록한다. I00/I01 완료가 ContextCompiler·멀티 Agent·Persona·RuleEngine·ExplainTrace·운영 완료를 뜻하지 않는다.

## 6. 매 PR 보고와 롤백

```text
PR / branch / base SHA / tested SHA:
변경 전 동작과 확인 방법:
범위 IN / OUT:
실제 변경 파일 / migration:
핵심 인터페이스와 schema:
실행한 test command / pass·fail·skip·중단 결과:
기존 Fact·Evidence·Claim·Plan·Portfolio·Review·Lock·Freeze·Submission 호환성:
namespace·권리·동의·원문 노출 평가:
미완료·blocker / 다음 PR 의존성:
feature flag 기본값 / rollback:
실제 모델·staging·production 수행 여부:
```

main 직접 수정·자동 병합·운영 자동 배포를 하지 않는다. 기존 v3/v4.1 브랜치는 보관하고 새 PR과 대체 관계를 명시한다. 공유 이력을 force push/reset으로 덮지 않으며, 필요한 증분을 revert하거나 기능 설정을 OFF로 돌린다. I00/I01에는 DB 파괴·마이그레이션이 없고 기존 사용자 원형·상태를 바꾸지 않는다.
