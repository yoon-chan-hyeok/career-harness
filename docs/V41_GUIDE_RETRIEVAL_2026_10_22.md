# v4.1 첫 증분 — 가이드 인벤토리와 오프라인 검색

사용자가 2026-10-22 제공한 `Career_Harness_v4_1_Question_Guide_RAG_Integration_SPEC.md`를 구현 요구의 입력으로 검토했다. 문서에 적힌 미구현 기능이나 수치를 현재 서비스의 완료 사실로 취급하지 않는다. 구현은 작은 브랜치·PR로 이어가라는 사용자 결정에 따라 분리한다.

`codex/v41-guide-retrieval`은 `codex/v3-experience-shadow`의 `9941043` 위에서 시작한다. 먼저 [v3 PR #1](https://github.com/yoon-chan-hyeok/career-harness/pull/1)을 검토하고, 이 증분은 후속 PR로 검토한다. 운영 설정이나 main을 자동 갱신하지 않는다.

## G0: 실제 자료

- 저장소 `backend/career/assets/writing_guides/`에는 포스코DX SW 개발 600자 가이드 **1건**이 있다. 877건 코퍼스는 확보되지 않았다.
- 기존 원문 연결과 `70/120/280/130` 배분, 592자 예시 회귀 검사를 유지했다. 기존 `writing_plans.guide_for` 동작을 변경하지 않았다.
- 새 수입기는 이 가이드를 명시적인 legacy adapter로 읽었다. 정규화된 버전 지문은 `09f69cbb475d07ed85296e75e8180a61c59e8dc9795f308ddc1a44b160d63e2d`다.
- 새 경로의 상태는 `IMPORTED_NOT_GLOBALLY_APPROVED`, `REVIEW_REQUIRED`, `source_verified_live=false`다. 원문의 검토 표시를 현재 서버의 권리·내용 승인으로 승격하지 않았다. 외부 원문을 새로 확인하거나 이용 허락을 취득한 기록은 없다.
- 변환 자료는 Git에서 제외되는 `private_input/v41-guide-catalog/`에 보관했다. 실제 개인 경험 DB나 취업 문서는 읽지 않았다.

## G1: 이번 구현

| 구성 | 구현 내용 |
|---|---|
| `question_contracts.py` | 현재 문항 원문·요구·제외 주제·길이·공백/줄바꿈/제목/바이트 정책 계약. 불명확한 정책은 UNKNOWN 유지 |
| `question_guide_import.py` | UTF-8/JSON 검증, 중복 키·비정상 값·크기 제한, 원본 보존, 정규화 필드의 출처 경로, 계산된 해시, 동일 ID/버전 충돌 차단, 최신 버전 선택 |
| `question_guide_search.py` | 가이드 전용 BM25, 선택 가능한 벡터 검색 어댑터와 순위 결합, 문항 유형·명시 요구·부정 조건·계수 방식·권리/대상 범위 검사, 최대 3개 후보 및 배제 사유 |
| `question_guide_cli.py` | 로컬 `import`, `inventory`, `search`. DB·외부 AI·배포에 접근하지 않는 관리 도구 |

`original_source`에는 수입 원형을 남기고 `derived_family`는 별도 휴리스틱 분석으로 기록한다. 외부 가이드 문장의 지시를 실행하지 않는다. 가이드 ID를 파일 경로로 사용하지 않으며 버전 파일은 덮어쓰지 않는다. 저장 레코드를 다시 읽을 때도 원본·해시·분석·출처를 재검증한다.

권리와 내용 검토는 수입 JSON과 분리된 `ReleaseLedger`로 공급한다. 가이드 ID·버전·전체 내용 해시가 일치하고 `STRUCTURE_ONLY_APPROVED`인 항목만 검색 후보 텍스트를 반환한다. 이는 운영자용 오프라인 검토 계약이며, 일반 사용자가 POST로 승인할 수 있는 API를 만든 것이 아니다. 이번에 실제 외부 가이드의 공개 사용을 새로 승인한 적은 없다. CLI 기본 검색은 미승인 자료를 제외하고 템플릿으로 돌아간다.

회사·직무·문항·현재 한도·알려진 계수 정책이 일치하면 `EXACT`, 검토된 구조 참고 후보는 `ADVISORY_ANALOGY`다. 둘 다 `approved=false`, 전체 결과는 `can_execute=false`다. 후보 선정은 Persona·Claim 승인과 다르다. 공백 등 기준이 불명확하면 EXACT로 판정하지 않고 확인 필요 상태를 남긴다. 따라서 기존 mini-kit의 보존된 정확 일치 경로와 새 경로의 더 엄격한 계수 정책 확인은 별개다.

현재 800자 문항에서 600자 원문의 기능을 참고하면 `source_allocation`은 원문 값을 유지하고 `suggested_allocation`만 현 제한으로 재계산한다. 새로운 제안임을 표시한다. 문자/바이트 단위가 다르거나 알려진 계수 정책이 충돌하면 후보에서 제외한다. 모든 후보 응답에서 예시 전문은 제외하며, 기존 예시의 수치를 개인 사실로 입력하는 경로를 추가하지 않았다.

벡터 검색·재판정 모델은 실제로 연결하지 않았다. 어댑터와 합성 점수로 순위 결합/오류 처리를 검증했으며 기본 실행은 BM25만 사용한다. 점수는 확률이나 검증된 품질 임계치가 아니다. 현재 적합성은 유형·필수 요구·부정 조건에 대한 보수적 구조 검사이고, 의미적 요구 일치의 정밀 판정은 후속 작업이다. 입력 지침과 개인 근거를 합치는 실제 모델 Context Compiler도 아직 구현하지 않았다.

## 로컬 사용

저장소 가상환경에서 다음처럼 실행한다. 수입 원본과 검토 대장은 `private_input/` 안에 둔다. 공개 저장소에 개인 자료나 미허가 전문을 추가하지 않는다.

```sh
python -m career.question_guide_cli import private_input/guide.json --catalog private_input/guide-catalog
python -m career.question_guide_cli inventory --catalog private_input/guide-catalog
python -m career.question_guide_cli search private_input/question.json --catalog private_input/guide-catalog
```

정규화 수입 형식은 `GuideInput`, 현재 문항은 `QuestionContract`다. 실행 가능한 합성 입력은 `tests/test_question_guide_retrieval.py`의 `source()`와 `question()`에 있다. 기존 가이드 원형을 가져올 때만 `--legacy-mini-kit`을 명시한다. 권리·내용을 사람이 확인한 구조 참고 자료는 별도 `ReleaseLedger` 파일을 `search --releases private_input/guide-releases.json`으로 전달할 수 있다. 이 옵션은 원문 예시 전문의 표시를 허용하지 않는다.

## 다음 증분

1. G2: 인증·소유권 확인 API와 가이드 선택 화면, 서버 버전 기반 선택 저장, 사용자 편집 가능한 문항 내부 예산.
2. G3: 현재 문항 요구·가이드 힌트·개인 E-RAG를 함께 쓰는 다문항 배분과 별도 승인. 이번 G1에서는 개인 근거 검색이나 새 배분 실행을 추가하지 않았다.
3. G4: 승인된 단일 guide snapshot을 WritingPlan/Brief/Writer가 공유하고 변경 시 stale 처리. 섹션별 실제 선택·규칙 적용 기록을 Why 화면으로 연결.
4. G5: 실제 모델의 기능 인수, 현재 지원 폼 계수 확인, 입력 예산 및 단계별 롤백 확인. 사용자가 제외한 성능 비교 실험은 다시 출시 의무로 넣지 않는다.

새 G-RAG는 아직 제품 API/화면/Writer와 연결하지 않았으므로 서비스 전체 적용 또는 v4.1 출시 완료가 아니다. 사용자 화면에 들어가는 G2부터는 작성 힌트와 문항 간 경험 배분을 서로 다른 승인으로 유지한다. `QUESTION_GUIDE_RAG_ENABLED` 운영 설정도 아직 추가·활성화하지 않았다.

## 검증과 되돌리기

합성 코퍼스로 수입 충돌·해시 위조·권리 위조·EXACT/유사/무매칭·실패/협업 오분류·600→800자·계수 정책·벡터 장애·외부 예시 미노출·선택 비승인·결정적 버전 지문을 검사한다. 기존 WritingPlan 회귀도 함께 검사한다. 최종 수치는 `IMPLEMENTATION_STATUS.json`과 해당 PR의 CI에 기록한다.

로컬 최종 전체 Python 검사 852개가 통과했다. PostgreSQL 전용 9개는 원격 CI에서 별도로 실행한다. 이 중 새 가이드 검사 38개와 기존 WritingPlan 17개가 모두 통과했고, Ruff·전체 Pyright·개인정보/소스 검사도 통과했다. 실제 보유 1건의 로컬 수입·인벤토리·미승인 자료 fallback도 확인했다. 외부 모델이나 유료 API는 호출하지 않았다. 원격 빌드와 실제 PostgreSQL 검증 결과는 후속 PR에 남긴다.

이 증분은 DB 마이그레이션이나 기존 실행 경로 변경이 없다. 후속 PR을 병합하지 않거나 해당 구현 커밋을 revert하면 된다. 이미 공유한 커밋을 강제 덮어쓰지 않는다. 로컬의 수입 원본은 별도 자료이며 코드 revert가 삭제하지 않는다. 검토 대장을 빼면 해당 자료는 즉시 검색 후보에서 제외된다.
