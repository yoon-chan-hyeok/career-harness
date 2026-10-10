# Career Harness

근거를 확인한 뒤 자소서와 레쥬메를 작성하는 개인 취업 작업실입니다. 회사 조사 → 경험·근거 연결 → 전략 승인 → 문항 설계·작성 → 검수 답변 → 제출 전 직접 확인 → 최종본 보관·면접 준비를 지원합니다. FastAPI·SQLAlchemy와 Next.js로 구성하며, MCP는 동일한 코어의 어댑터입니다.

2026-10-10 최신 검증: Python 642개 통과, 별도 PostgreSQL 환경 검사 6개 미실행, 프런트엔드 26개 통과 및 production build 완료. 조사·승인 표현 보관·제출 전 확인을 합성 브라우저에서 검증했습니다. **전체 명세 인수와 실제 외부 AI·운영 배포는 진행 중입니다.**

- [로컬 실행](RUN_LOCAL.md)
- [회사 조사·표현 재사용](docs/RESEARCH_AND_EXPRESSION_PROGRESS_2026_10_10.md)
- [직업 정체성·제출 전 세 질문 및 남은 작업](docs/FINAL_REVIEW_PROGRESS_2026_10_10.md)
- [공개 가입형 운영 준비](docs/PUBLIC_SERVICE_SETUP.md)
- [전체 구현 상태](IMPLEMENTATION_STATUS.json)

GitHub 소스에는 개인 자료·DB·접속 토큰·API 키가 포함되지 않습니다. 새 환경에서 자료를 등록하고 AI 제공자를 직접 연결해야 합니다. 직접 작성 모드는 외부 AI 없이 사용할 수 있으며, 최종본 보관과 실제 제출 확인은 별도입니다.

아래는 제공된 v2.2 구현 팩의 원래 설계 안내입니다.

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
