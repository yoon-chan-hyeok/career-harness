# I01 후속 — 보안 기준선과 가이드 전문 공개 경계

사용자의 2026-10-23 다음 단계 요청에 따라 I02 착수 전 차단 사항을 보완한다. 기반은 PR #4 / 737b335이며 main·기존 v3/v4.1 브랜치는 그대로 둔다.

## 실제 변경

- `frontend/package.json`, `frontend/package-lock.json`: Next.js와 eslint-config-next를 15.5.27 → 15.5.28로 최소 패치. [공식 릴리스](https://github.com/vercel/next.js/releases/tag/v15.5.28)의 보안 수정이다. 기존 sharp/postcss override와 CI 보안 기준 유지.
- `backend/career/guide_publication.py`: 권리 미확인 ARCHIVED_REFERENCE의 전문·원문 인용을 제거하는 복사본 투영. 배분·문항 의도·출처/해시는 보존. 입력의 PUBLIC_APPROVED 표시로 공개 허용하지 않음.
- `backend/career/writing_plans.py`: 새 preview/persist/Writer가 같은 공개용 snapshot과 hash 사용. 과거 원문 snapshot의 revision은 새 정책과 달라 재확인 필요. `guide_for()` 원형·70/120/280/130·7종 fallback 유지.
- `backend/career/truth.py`: 조회용 view만 중첩된 과거 guide를 투영해 application/history/trace/export에서 같은 전문이 새지 않음. Truth 저장·승인·소유권 함수는 불변.
- `frontend/app/writing-plan-panel.tsx`: 예시 전문 대신 공개 권리 확인 중이라는 안내와 출처 표시.
- `tests/test_guide_publication.py`: 투영 불변성·권리 표시 주입·exact 화면/Writer·기존 Claim Test/승인 경유·과거 계획 재확인·Frozen 불변·HTTP/trace/export/사용자 격리 회귀.
- `AGENTS.md`, `IMPLEMENTATION_STATUS.json`, `docs/UNIFIED_ACCEPTANCE_TEST_MATRIX.csv`, 이 문서: 실제 실행 결과와 후속 의존성.

## 실제 검증

`pytest tests/test_guide_publication.py tests/test_writing_plans.py tests/test_writing_plans_api.py`: 새5개 포함24개 통과. 기존 작성 흐름은 Claim Test와 승인 뒤 FakeLLM Writer까지 실제 실행했다. 실제 모델 호출은 없다.

Ruff/Pyright 통과. frontend lint/types 및 기존 Node 검사30개 통과. production build 성공(기존 CSS autoprefixer 경고는 남음). `npm audit --omit=dev --audit-level=high`: 0건. 전체 audit의 개발 의존성 high5건은 이 결과에 포함되지 않으며 별도 유지보수 대상이다. 원격 전체 pytest·PG·migration·frontend 결과는 PR에 고정 SHA로 기록한다.

API GET/POST와 화면이 읽는 구조·Provider 입력 snapshot을 합성 HTTP/Workflow와 frontend 타입·빌드로 검증했다. 실제 운영 UI 브라우저 인수·운영 배포는 하지 않았다.

## 호환성·범위·다음 의존성

AC-012는 **실행 경로의 미허가 전문 비노출** 기준으로 PASS다. 원문의 공개 재배포 권리를 취득했다는 뜻이 아니다. 기존 저장본·SubmissionBundle의 원형과 감사 해시는 바꾸지 않으며 외부 응답만 투영한다. 공개 저장소의 과거 커밋/기존 원문 자산 권리 자체는 이번 코드 변경으로 승인되지 않는다.

필수 Fact/Evidence·Claim Test·WritingPlan·QuestionPortfolio·Review·Lock·Freeze·Submission Gate는 유지한다. 가이드 내용이 달라진 기존 작성계획은 재확인하며 자동 승인하지 않는다. DB migration·실제 AI·운영 환경 변경 없음. 가이드 검색은 기본 OFF.

이 PR 전체 CI를 확인한 뒤 I02 Context/Experience/Shadow를 별도 PR로 진행한다. I03 선택 API·Guide 저장·Persona·Rule/Trace 실행은 이번 범위가 아니다. 롤백은 전용 커밋 revert이며 DB rollback은 불필요하다. 전문 비노출 수정은 보안 수정이므로 이전 정책으로의 복귀에는 원문 권리 검토가 필요하다.
