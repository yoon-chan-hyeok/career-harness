# I02 — 사용자별 Context와 읽기 전용 계획

2026-10-23 사용자의 다음 단계 진행 요청에 따라 통합 handoff의 I02를 구현한다. 기반은 `codex/i01-readiness-fixes` / `7507319`, [PR #5](https://github.com/yoon-chan-hyeok/career-harness/pull/5)다. 해당 SHA의 [CI39892050961](https://github.com/yoon-chan-hyeok/career-harness/actions/runs/39892050961)는 Python873/PG 전용9 skipped와 별도 실제PG9, MCP, migration 왕복/check, Ruff/Pyright/privacy, frontend30/lint/types/build·production audit0를 통과했다. I00/I01의 기존 차단은 이 기준에서 보완됐으며 원문 재배포 권리는 취득한 것이 아니다.

## 실제 변경 파일

| 파일 | 변경 |
|---|---|
| `backend/career/v3_contracts.py` | 원래9941043의 계약 재사용. 통합 이름 ExperienceCardProjection과 기존 ExperienceCard alias. Rule/SectionTrace는 기존 선언만 보존하며 이번에 실행하지 않음 |
| `backend/career/v3_preview.py` | 원래9941043의 경험·Shadow 조회 재사용. DynamicPlanPreview alias, 철회 자료 거부, SKIPPED 필수 단계 명시 BLOCKED |
| `backend/career/scoped_context.py` | ContextRequest·ScopedContextManifest·ContextPack와 순수 read-only compiler |
| `backend/career/api.py` | 인증·소유권을 재사용하는 기본 OFF v4 preview 경로3개와 입력 오류 비노출 |
| `.env.example` | CAREER_CONTEXT_PREVIEW_ENABLED=0 |
| `tests/test_v3_contracts.py`, `tests/test_v3_preview.py` | 기존 PR #1 검사 재사용. 원래 브랜치는 보존 |
| `tests/test_scoped_context.py`, `tests/test_context_preview_api.py` | 작업 범위·자료 최신성·권한·예산·삭제·승인·HTTP·불변성 회귀 |
| `docs/I02_SCOPED_CONTEXT.md`, `docs/UNIFIED_ACCEPTANCE_TEST_MATRIX.csv`, `AGENTS.md`, `IMPLEMENTATION_STATUS.json` | 실행 결과·호환성·미완료·후속 의존성 |

원래 v3 파일명과 `v3-preview-1` 계약 버전은 재사용 이력을 위해 보존한다. 제품은 같은 Career Harness이며 API는 통합 `/api/v4`에서 제공한다. v3 프로젝트나 새 Truth 저장소를 만들지 않았다. ExperienceCard·ContextPack은 조회 시 생성하고 DB에 저장하지 않는다.

## 인터페이스

`GET /api/v4/experience-cards/{evidence_id}`는 JD 없이 현재 Evidence·Source·관련 Ownership/Metric/ClaimBoundary/DecisionEpisode의 ID/상태/지문을 읽는다. 본문은 기존 Evidence의 조회 투영이며 수정·승격하지 않는다. 미확인은 경고와 원래 상태를 표시하고, DO_NOT_USE 자료는 거부한다.

`GET /api/v4/applications/{workspace_id}/plan-preview?intent=APPLICATION|RESUME_ONLY|INTERVIEW_ONLY`는 현재 자료와 기존 Gate를 검토할 후보 단계를 반환한다. `can_execute=false`, `completion_proof=false`, mode SHADOW_ONLY다. 과거 결과는 REUSE_CANDIDATE이며 실제 완료 증명이 아니다. 필수 단계의 SKIPPED는 BLOCKED, 실패/낡은 Claim Test·Review·사람의 HOLD·미답변은 후속 진행을 막는다. 동결은 실제 제출로 표시하지 않는다.

`POST /api/v4/context/preview`는 body로 작업과 scope만 받으며 인증 사용자는 서버가 정한다. 입력 user_id/namespace/vector/approval 필드는 거절한다. read-only POST이며 Provider/operation executor·예산 차감·PromptRun·저장 이벤트를 만들지 않는다. 실제 운영 인증·rate-limit 부수 기록은 기존 보안 체계에 속하며 Context의 제품 상태 변경으로 혼동하지 않는다.

```json
{
  "task_type": "COVER_WRITE",
  "application_id": "본인-지원-ID",
  "question_id": "해당-지원의-문항-ID",
  "required_evidence_ids": ["본인-근거-ID"],
  "expected_revisions": {},
  "max_input_tokens": 8192,
  "external_transfer_consent": false
}
```

| 작업 | 포함 가능한 자료·기준 |
|---|---|
| EXPERIENCE_REVIEW | 명시 경험만, JD 불필요, 미확인 원형을 확인 상태와 함께 조회. 프로필 사실·지원 scope 혼입 거절 |
| JOB_ASSESS | 현재 지원/JD와 명시한 본인 근거·canonical 프로필 사실. 작성 선호·전략·다른 문항 제외 |
| QUESTION_PORTFOLIO | 현재 지원의 전체 문항, 명시 근거, 현재 EvidencePack·잠긴 전략, 범위에 맞는 명시 선호 |
| COVER_WRITE | 해당 지원의 지정 문항·현재 제한, 그 Brief와 같은 근거 ID 집합, 현재 EvidencePack·잠긴 전략, 관련 명시 선호 |
| RESUME_WRITE | 현재 지원, 명시 근거·canonical 프로필 사실, EvidencePack·잠긴 전략, RESUME/COMMON 선호 |

모든 writing 작업의 근거는 현재 EvidencePack의 DIRECT/ADJACENT 범위와 확인 상태·소유 수행 범위를 다시 확인한다. 동결/제출/종료 작업은 HOLD다. 전체 모델 입력 연결은 아직 없으며 INPUT_READY_OFFLINE은 이 조회 입력의 준비 상태다. Claim 승인·문서 생성·최종 잠금을 허용하는 상태가 아니다.

선호는 기존 WritingRuleRecord의 USER_DIRECTIVE와 원래 fingerprint/source 검증을 재사용한다. 회사·직무·프로젝트·문항 유형·산업 및 COVER/RESUME domain을 제한한다. 학습 후보·전역 규칙·다른 사용자·범위 밖 선호·미승인 변경은 포함하지 않는다. Persona 확정이나 새 VoiceProfile 쓰기 기능은 추가하지 않았다.

Manifest는 owner/task/scope, 자료 ID·version·status·hash, 누락 사유, 예산을 담는다. 원문은 manifest나 로그에 복제하지 않고 응답 payload에만 둔다. model/prompt는 미선택이며 consent는 NOT_EVALUATED_NO_EXTERNAL_TRANSFER다. 외부 전송은 항상 false이고 consent=true 입력도 거절한다. 이후 I06/I08에서 실제 실행 시 기존 동의/예산/Provider 검증을 다시 거쳐야 한다.

`expected_revisions`의 `KIND:ID`가 현재 scope에 없거나 hash가 바뀌면 409다. 토큰은 기존 로컬 GPT-OSS BPE·여유분으로 전체 payload를 추정하며 실제 Provider 사용량이 아니다. 필수 근거·질문을 조용히 잘라내지 않는다. 예산 초과나 필수 공백은 HOLD와 전체 payload=null로 반환한다. 선택하지 않은 원문으로 보충하지 않는다. 새 approved_rule_pack_version은 I02에서 해결할 수 없으므로 HOLD로 표시하며 246개 원칙을 활성화하지 않는다.

## 실행 검증

최종 로컬 대상 검사 **87 passed / 26.67초**. Ruff/Pyright(0 errors/warnings)·privacy·staged diff 검사 통과. 원격 전체 결과는 PR의 고정 SHA로 추가한다. 실행 명령:

```sh
pytest tests/test_v3_contracts.py tests/test_v3_preview.py tests/test_scoped_context.py tests/test_context_preview_api.py tests/test_writing_plans.py tests/test_writing_plans_api.py tests/test_claim_test.py tests/test_portfolio_plan.py
ruff check .
pyright
python scripts/check_privacy.py
```

검사는 합성 SQLite·가짜 Provider만 사용한다. SQL 이벤트로 compiler/Shadow에서 SELECT 이외의 문장이 없는지 확인하고 dirty Session을 거절한다. 반복 결과·버전·payload 불변성, 사용자 간 교차 참조, 다른 지원 문항, 미승인 경험/선호, 필수 누락, SKIPPED, 예산 초과, 동결·제출·종료 경계와 기본 OFF·인증·권리 주입을 검사한다. 전체 pytest/MCP·실제 PG·migration·frontend는 GitHub CI에서 확인한다. 운영 DB·개인 원문·실제 모델·실제 운영 브라우저 인수·배포는 사용하지 않았다.

## 호환성·미완료·다음 의존성

기존 Fact/Evidence·Claim Test·WritingPlan·QuestionPortfolio·Review·Lock·ready/freeze/confirm_submission 실행 코드는 변경하지 않는다. models·migrations·기존 API 경로·frontend도 이번 I02에서 바뀌지 않는다. 별도 저장/Agent DB·자동 Rule APPLIED·동적 executor는 없다. 롤백은 I02 커밋 revert 또는 기본 OFF이며 DB rollback이 필요 없다.

AC-015~019는 실행 증거에 맞춰 기록한다. I03+ 항목은 NOT_RUN을 유지한다. I03은 이 scope/version 인터페이스를 사용해 현재 QuestionContract·Guide 선택·WritingPlan snapshot/API/UI를 연결해야 한다. 이후 다문항 배분/Persona 결정·실제 Rule/Trace·Writer 실행·외부 전송 동의·운영 인수는 통합 PR 순서로 진행한다. 새로운 전용 VoiceProfile 저장/편집, 의미적 Context 선택, 실제 모델 입력 품질·운영 성능은 이번 완료 범위가 아니다.

main 자동 병합·운영 자동 배포는 하지 않는다. PR 보고는 변경 파일·실행 검사·기존 호환성·미완료와 다음 의존성을 유지한다.

## 고정 코드·검사 SHA의 최종 CI 결과

검증한 SHA `2e1df61265da962414cf3fb09fa2ecd747785433`, [CI39893880397](https://github.com/yoon-chan-hyeok/career-harness/actions/runs/39893880397)는 backend/frontend 모두 SUCCESS다. 전체 Python **928 passed / PG 전용9 skipped**, 별도 실제 PostgreSQL **9 passed**, MCP·migration upgrade/check/downgrade/upgrade·Ruff/Pyright/privacy와 frontend30/lint/types/build·production audit0를 통과했다. 로컬87개 인수도 통과했다. 이 결과를 기록한 후속 커밋은 문서만 변경하며 코드·검사는 위 SHA와 동일하다. 문서 HEAD의 자동 CI와 위 고정 검증 결과는 구분한다.

현재 인수표는 I00~I02의19개 PASS, I03 이후34개 NOT_RUN이다. PR은 draft/unmerged, 기능은 기본 OFF다. main4202b86·원래 v3 9941043·v4.1 26d89a9 보존을 확인했다. 실제 모델·개인 데이터·운영 배포 수행은 없다.
