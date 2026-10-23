# I01 — 통합 Question Guide 오프라인 계약

기준은 통합 MASTER_HANDOFF_20261022와 I00 PR #3이다. 구현 브랜치는 `codex/i01-unified-guide`, 기반은 `codex/i00-unified-inventory` / `d4e1689`다. 원래 가이드 커밋 `26d89a9`의 네 모듈과 검사를 재사용하되, I02 후보인 v3 코드/API/설정은 가져오지 않았다.

## 변경 파일과 동작

| 파일 | 실제 변경 |
|---|---|
| `backend/career/question_contracts.py` | 현재 문항·요구·제외 주제·계수 정책·revision. 기존 v4.1 그대로 재사용 |
| `backend/career/question_guide_import.py` | 명시적 legacy 수입, 원본·버전·해시 보존, 개인 namespace 재귀 차단, SourceManifest·권리 분리, 상충 검토 거절 |
| `backend/career/question_guide_search.py` | exact 우선, BM25/사전 점수, 부정 요구·scope·필수 조건 필터, GuideCandidate·7종 fallback, 기본 OFF |
| `backend/career/question_guide_cli.py` | 로컬 import/inventory/search 및 명시적 opt-in |
| `tests/test_question_guide_retrieval.py` | 기존 38개 가이드 검사를 새 오프라인 계약에 맞춰 재사용 |
| `tests/test_guide_i01_contracts.py` | 통합 경계 회귀 45개 추가 |
| `.env.example` | `QUESTION_GUIDE_RAG_ENABLED=0`, 오프라인 CLI 용도 명시 |
| `docs/V41_GUIDE_RETRIEVAL_2026_10_22.md` | 원래 PR 이력·새 단계 순서 연결 |
| `docs/I01_UNIFIED_GUIDE.md` | 이 구현·검증·미완료 보고 |
| `docs/INVENTORY_AND_BASELINE.md` | 이번 CI 기준선 결과 추가 |
| `docs/UNIFIED_ACCEPTANCE_TEST_MATRIX.csv` | 실행 증거 연결, AC-012 범위 제한을 PARTIAL로 명시 |
| `AGENTS.md`, `IMPLEMENTATION_STATUS.json` | 후속 재개 기준·실제 결과·blocker |

마이그레이션 없음. 기존 제품 API·UI·Writer·Truth·Workflow·검사 파일은 변경하지 않는다.

## 인터페이스와 안전 경계

`SourceManifest`는 QUESTION_GUIDES namespace, 원본 payload 지문, 출처·scope, 권리 상태와 실행 허용을 분리한다. PUBLIC_APPROVED / PRIVATE_REFERENCE / RIGHTS_PENDING / RESTRICTED 네 상태를 명시한다. 별도 운영자 검토 대장은 구조 참고만 허용하며, 어떤 상태에서도 이번 응답의 예시 전문 공개는 false다. import JSON의 권리·검토 표시만으로 승인하지 않는다. 동일 ID/version/hash의 복수 검토는 순서와 관계없이 거절하여 먼저 등록한 허용 검토가 제한 검토를 우회하지 못하게 한다.

수입 원본과 저장 레코드는 읽을 때도 재검증한다. user_id/owner_id/workspace_id, Fact/Evidence 관련 메타데이터, USER_EVIDENCE 등 다른 namespace는 legacy의 중첩 객체·목록에서도 차단한다. 실제 Source/Evidence 모델도 공용 catalog에 넣을 수 없다. 기존 수입 레코드의 해시 형식은 바꾸지 않았다.

`GuideCandidate`는 질문·가이드 참조, request_key, EXACT/ADVISORY_ANALOGY, 매칭 정책, retrieval_mode, 선택 이유, SourceManifest를 담고 `CANDIDATE_NOT_APPROVED`다. 기존 개인 Claim/Persona/Portfolio 승인이나 상태 변경을 발생시키지 않는다.

검색 순서는 검토된 정확 일치 → 구조 참고 후보 → 필수 조건 필터 → fallback이다. exact가 있으면 lexical/vector 점수를 평가하지 않는다. 같은 원형의 LEGACY_EXACT는 70/120/280/130을 보존하지만 UNKNOWN 계수 정책은 확인 필요로 남긴다. 회사·직무·600→800자 변경은 EXACT가 아니다. 다른 자수의 구조 참고는 현재 제한에 맞춘 새 제안으로 표시한다.

`OfflineVectorScores`는 질문 revision·corpus revision·가이드 namespace·대상 ID·유한한 점수를 검증한 **데이터**다. 실행 callback·네트워크·임베딩 제공자를 호출하지 않는다. 없거나 무효면 LEXICAL_ONLY/fallback으로 돌아간다. 사전 점수가 있어도 `semantic_search_executed=false`이며 실제 의미 모델을 실행한 것으로 기록하지 않는다.

“협업 제외”, “협업이 아니라”, “협업 없이” 등의 부정 요구는 보수적으로 검토 필요/fallback 처리한다. 이는 정밀한 자연어 의미 판정 완료가 아니다. 877개 실제 코퍼스나 calibrated threshold 검증도 없다.

## 사용과 기본값

제품에 연결하지 않은 로컬 관리 도구다. 원형·검토 대장은 ignored private_input 아래에 둔다.

```sh
python -m career.question_guide_cli import private_input/guide.json --catalog private_input/guide-catalog
python -m career.question_guide_cli inventory --catalog private_input/guide-catalog
python -m career.question_guide_cli search private_input/question.json --catalog private_input/guide-catalog
# 아래는 별도 검토 대장을 공급한 로컬 명시 opt-in
python -m career.question_guide_cli search private_input/question.json --catalog private_input/guide-catalog --releases private_input/reviews.json --enable-guide-preview
```

기본 search는 FEATURE_DISABLED fallback이다. `--enable-guide-preview` 또는 정확히 `QUESTION_GUIDE_RAG_ENABLED=1`일 때만 새 검색을 켠다. 기존 writing-plan은 이 플래그와 무관하게 그대로 작동한다. import에는 기존 mini-kit adapter가 필요할 때만 `--legacy-mini-kit`을 지정한다. 실제 외부 자료의 권리 검토를 이번 작업에서 임의 생성하지 않았다.

## 검증

- 변경 전 SHA26d89a9의 WritingPlan/API·rulebook·portfolio·Claim Test·Review·Workflow: **106 passed**. 원래 브랜치에서 제품 수정 전에 실행.
- 새 경계와 재사용 가이드 검사: `pytest tests/test_question_guide_retrieval.py tests/test_guide_i01_contracts.py -q -p no:cacheprovider`: **83 passed**. 합성 자료와 기존 가이드 fixture만 사용.
- 정적 검사: `ruff check .`, `pyright --pythonpath <venv-python>`. 둘 다 통과(0 errors/warnings). 개인정보·git diff 검사 통과. 기존 핵심/API/UI/models/migrations는 main4202b86과 diff 0.
- 전체 로컬 실행: Windows MCP stdio 대기로 첫 시도를 중단했다. 해당 테스트 제외 후 재시도는 호스트 환경 전환 때 85%에서 종료돼 완료 결과가 없다. 둘 다 전체 통과로 계산하지 않는다. 저장소 테스트와 CI에 skip을 추가하지 않았다.
- I00 exact head d4e1689의 [CI 39888623254](https://github.com/yoon-chan-hyeok/career-harness/actions/runs/39888623254): 백엔드 전체 pytest(MCP 포함), 실제 PostgreSQL, 마이그레이션 왕복/check, Ruff/Pyright/privacy 성공.
- 같은 CI의 프런트엔드는 기존 Next.js 15.5.27에 대한 production npm audit에서 실패했다. 이후 frontend lint/type/tests/build는 SKIPPED다. 아래 보안 blocker가 해결되기 전 전체 CI 성공으로 표시하지 않는다.
- I01 최종 코드·검사 SHA `f8ef7ff429d4a410dccd26d3e815dea17bd94786`, [CI39890434876](https://github.com/yoon-chan-hyeok/career-harness/actions/runs/39890434876): **backend SUCCESS, 868 passed / PG 전용9 skipped**, 별도 실제 PG **9 passed**, MCP 포함, migration 왕복/check·Ruff/Pyright/privacy 성공. **frontend FAILURE**는 위 기존 의존성 audit이며 후속 frontend 검사 SKIPPED. 이 결과를 기록하는 후속 커밋은 문서만 변경하고 코드·검사는 동일하다. 전체 CI PASS는 아니다.

## 미완료와 다음 단계 의존성

1. **AC-012 PARTIAL:** 새 오프라인 응답은 예시 전문을 내보내지 않는다. 하지만 기존 `writing_plans.public_preview()`의 예시 전문 경로는 여전히 권리 검토 미완료다. 기존 snapshot 호환성을 임의 변경하지 않았다. I03의 제품 연결 전에 공개 권리·응답 투영·화면/Writer 일관성을 해결해야 한다.
2. **기존 의존성 CI blocker:** [Next.js RCE 권고](https://github.com/advisories/GHSA-2464-fhr4-w9xw), [Server Actions DoS 권고](https://github.com/advisories/GHSA-p3m5-59mp-jv5r)가 15.5.28을 패치 버전으로 명시한다. 현재 sharp override는 0.35.5이지만 audit은 Next.js 버전 범위를 차단한다. 이것만으로 운영 서비스가 실제 공격 가능하다고 판정하지 않는다. 이번 I00/I01 범위 밖의 의존성 수정·전체 프런트 재검증이 병합 전 필요하며 보안 검사 우회는 금지한다.
3. I02+ 39개 acceptance는 NOT_RUN이다. 기존 v3 PR #1은 I02 후보로 보존한다. 통합 인터페이스를 수용한 뒤 Context/Experience read model부터 검토해야 한다.
4. Guide 선택 저장·UI·사용자 Evidence RAG·다문항 배분·Persona/HITL·RuleEngine·ExplainTrace·Writer 연결·실제 모델·운영 인수는 구현 완료가 아니다. 246개 규칙과 외부 가이드의 공개 권한은 자동 활성화하지 않는다.

I00/I01 PR은 draft로 유지하며 main 직접 수정·자동 병합·운영 배포를 하지 않는다. 기능 OFF 또는 해당 커밋 revert로 되돌릴 수 있고 DB 되돌리기는 필요 없다. Fact·Evidence·Claim Test·WritingPlan·QuestionPortfolio·Review·Lock·Freeze·Submission의 원래 조건을 보존한다.
