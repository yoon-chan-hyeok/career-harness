# Implementation Status Protocol

`IMPLEMENTATION_STATUS.json` is the machine-readable checkpoint for Codex implementation sessions.

## Start/resume rule

At the beginning of every implementation session:

1. read `IMPLEMENTATION_STATUS.json`,
2. inspect the repository and verify claims for completed milestones,
3. run a lightweight verification for the last completed milestone,
4. resume from the first `pending` or `in_progress` milestone,
5. do not redo completed milestones unless verification fails or a dependency changed.

## Update rule

At the end of each milestone:

- mark milestone `complete`,
- set next milestone `in_progress` or leave pending until begun,
- update `last_completed_milestone`,
- update `current_milestone`,
- record verification results,
- record current git commit if available,
- add a concise note if a known limitation remains.

If interrupted mid-milestone:
- set that milestone `in_progress`,
- save notes about completed substeps and failing tests.

This file tracks implementation work only.
It is separate from runtime Application/Question state machines.

## 2026-10-02 checkpoint

추가 자료 6종의 단계별 기준, 사실/표현 분리, 버전별 사용자 결정, 수정안 승인·거절, 경험의 항목 선택·정정 출처, 이력서 마스터·파일 확인을 구현했다. 상세 범위와 검증은 `IMPLEMENTATION_REPORT.md`와 `docs/SUPPLEMENTAL_INTEGRATION_AUDIT.md`에 있다. 외부 AI 품질·PostgreSQL·Docker·Jev 수용 검증은 코드 구현 완료와 별개이며 `external_acceptance_pending`을 유지한다.

## 2026-10-03 scope override

최신 사용자 결정은 `docs/USER_DECISIONS.md`가 우선한다. 비교·성능 개선·업그레이드 실험은 이번 범위와 출시 조건에서 제외한다. M12의 외부 비교 실험을 pending release gate로 유지하지 않는다. 레쥬메, HF/Groq 생성 연결, 역할별 자료 경계, 개인 AI 설정과 기능·보안·장애 검증은 이번 범위에 포함한다. HF 도구 계정 연결과 앱 추론 토큰·실호출 확인은 구별한다. 현재 결과는 JSON checkpoint와 `IMPLEMENTATION_REPORT.md`를 확인한다.

## 2026-10-03 follow-up audit correction

추가 작업 감사에서 AI 레쥬메 분량 옵션 누락, 무료 제공자의 PostgreSQL 검색 후보 누락, 여러 AI 호출의 전체 요청 시간 제한 부재, 긴 입력의 사전 제한 부재를 확인했다. 기존 검사 통과는 보존하되 전체 코드 완료 표현을 정정하고 M4/M8/M14의 구현 보완을 다시 진행 대상으로 기록했다. 이번 감사는 수정과 전체 검사 재실행을 하지 않았다. 다음 작업 전 `docs/REMAINING_WORK_AND_UPGRADES.md`와 JSON의 `remaining_work_audit`를 확인한다. 사용자 입력이 필요한 연결 작업과 독립적으로 수정 가능한 코드 작업을 구별한다.


## 2026-10-03 upgrade checkpoint

필수 보완 4건과 업그레이드 6종을 구현했다. Python 339 통과/PG 3개 미실행, 프론트엔드 15개 검사 및 최신 lint/typecheck/build, 실제 UI/HTTP/파일/SQLite 복구를 확인했다. 현재 기록은 `docs/UPGRADE_PROGRESS.md`와 JSON의 `upgrade_progress`다. 실제 HF 작성·운영 PG/Auth·HTTPS·운영 복구/CI·Word 페이지 렌더는 남아 있어 전체 완료로 표시하지 않는다.


2026-10-03 추가 실DB/소스 감사: Python 353 통과와 별도 실제 PG 3 통과, PG16 migration 왕복·보호 적용·39개 테이블 복구/내용 일치 확인. 공개 회귀 사례 비식별 합성 교체와 미추적 소스 개인정보 검사 보강. 운영 계정 연결과 Word 페이지 검증은 미완료. 최신 상세 상태는 docs/UPGRADE_PROGRESS.md.
