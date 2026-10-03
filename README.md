# Career Harness — Codex One-Shot Implementation Pack v2.2 FINAL

로컬 구현을 실행하려면 [실행 안내](RUN_LOCAL.md)를, 구현 범위와 남은 검증은 [구현 현황](IMPLEMENTATION_REPORT.md)을 확인하세요. 아래는 제공된 원본 구현 팩 안내입니다.

이 패키지는 사용자가 GPT와 수동으로 수행하는 취업 준비 절차를
프로덕션 수준의 반복 가능한 AI workflow로 자동화하기 위한 최종 구현 명세다.

핵심 목표:

> 사용자가 매번 "JD 분석해 → 회사 조사해 → 내 자료 찾아 → 과장 확인해 → 전략 정해 → 자소서/레쥬메 써 → 채용자 입장에서 다시 봐"라고 지시하지 않아도,
> 시스템이 그 절차를 기본 동작으로 수행한다.

## v2.2 FINAL에서 잠근 핵심

- M0/M1 구현 순서 정합성 수정
- OpportunityBrief = 회사/직무 측 정보만
- ApplicationBrief = Evidence 기반 지원 전략/Gap/Assignment
- SUBMISSION_FROZEN ≠ 실제 SUBMITTED
- InterviewHandoff = SubmissionBundle의 별도 downstream artifact
- OpenAIWebResearchProvider를 기본 live research adapter로 명시
- production telemetry tables 명시
- UI를 vertical slice마다 조기 구현
- CapabilityRecord는 ordinal evidence-backed 상태
- Resume는 structured + Markdown + HTML preview까지 v0.1

## Codex 시작

1. 폴더 전체를 workspace/repository로 연다.
2. `CODEX_MASTER_PROMPT.md`를 한 번 전달한다.
3. `IMPLEMENTATION_STATUS.json` 기준으로 순차 구현/재개한다.

## Canonical order

1. AGENTS.md
2. IMPLEMENTATION_STATUS.*
3. IMPLEMENTATION_PLAN.md
4. docs/00_PRODUCT_SCOPE.md
5. docs/04_ARTIFACT_SCHEMAS.md
6. docs/05A_STATE_MACHINE_SPEC.md
7. docs/06A_WEB_RESEARCH_SPEC.md
8. 나머지 상세 docs
9. tasks/
10. source_specs/

이 버전을 설계 종료선으로 취급한다.
추가 기능은 실제 사용 후 별도 change request로 다룬다.
