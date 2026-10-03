# AGENTS.md — Career Harness

## Mission

현재 사용자 범위와 예외는 `docs/USER_DECISIONS.md`를 먼저 확인한다. 이 파일은 2026-10-02 직접 사용자 요청을 기록하며, 이전 문서의 비교/개선 실험 의무보다 우선한다. 서비스 작동과 레쥬메 흐름은 포함하고 비교/업그레이드 실험은 이번 범위에서 제외한다.

후속 코드 감사와 추가 작업은 `docs/REMAINING_WORK_AND_UPGRADES.md`, `IMPLEMENTATION_STATUS.json`의 `remaining_work_audit`에서 확인한다. 미수정 보완이 있으면 이전 코드 완료 기록이나 검사 수만으로 계정 연결만 남았다고 판단하지 않는다.
이 감사 후 실제 업그레이드 구현·남은 검증은 `docs/UPGRADE_PROGRESS.md`와 `IMPLEMENTATION_STATUS.json`의 `upgrade_progress`가 현재 기록이다. 이전 감사의 미구현 상태 및 과거 검사 수와 구별하며 최신 UI·Word 렌더·운영 PostgreSQL·실제 계정 연결을 확인하지 않고 전체 완료로 표시하지 않는다.

이 repository는 Career Harness를 구현한다.

목표는 일반적인 "AI 자소서 생성기"가 아니다.

사용자가 GPT와 취업 준비할 때 반복 수행하던
직무 해석 → 근거 검색 → 전략 결정 → 글 작성 → 검증 → 수정 → 제출 → 학습
절차를 시스템이 기본적으로 수행하게 만든다.

## Mandatory principles

1. **Write after proof**
   - Evidence/Claim이 확정되기 전에 최종 문서를 작성하지 않는다.

2. **Truth over fluency**
   - 잘 쓴 문장보다 Fact / Ownership / Metric / Source 정확성이 우선한다.

3. **Persona is derived**
   - JD와 Evidence 분석 전 Persona를 고정하지 않는다.

4. **Keyword match is not job fit**
   - Actual Output / Main Skill / Direct Evidence / Fatal Gap을 본다.

5. **Fact Store and Expression Store are separate**
   - 과거 자소서의 오래된 사실이 현재 Truth를 덮지 못한다.

6. **Agent != microservice**
   - 역할이 다르더라도 동일 backend의 다른 prompt/context 함수로 구현 가능하다.
   - 불필요한 autonomous multi-agent runtime을 추가하지 않는다.

7. **Artifact + Workflow first**
   - Chat transcript를 workflow source of truth로 사용하지 않는다.

8. **No silent overclaim**
   - source 없는 수치, ownership 확대, project contribution 확대를 금지한다.

9. **User correction changes state**
   - "이건 내가 한 게 아님", "RAG 빼", "이건 Adjacent" 같은 correction은
     구조화된 Artifact patch로 반영한다.

10. **Outcome attribution is conservative**
    - 합격/탈락은 weak signal이다.
    - 코테 탈락을 자기소개서 실패로 학습하지 않는다.

## Architecture

Start as a modular monolith.

Preferred stack:
- Python 3.12
- FastAPI
- Pydantic v2
- SQLAlchemy 2.x
- PostgreSQL 16+
- pgvector
- Alembic
- pytest
- Ruff
- Pyright
- Next.js / TypeScript for UI
- Docker Compose
- GitHub Actions

MCP is an adapter over Career Core, not the business logic layer.

## Dependency direction

UI / REST / MCP
↓
Application Services / Workflow
↓
Domain
↓
Repositories / Retrieval
↓
PostgreSQL / External providers

LLM provider code must stay behind interfaces.

## QA before milestone completion

Run:
- `ruff check .`
- `pyright`
- `pytest`
- frontend lint/typecheck/build when frontend exists
- migration checks
- relevant end-to-end workflow test

Do not continue to the next milestone with a broken previous milestone.

## Privacy

Never commit:
- raw ChatGPT exports
- real resumes
- API keys
- credentials
- private application documents
- private database dumps

`private_input/` is local seed/import data and must be gitignored.

## Scope discipline

Do not add:
- Kubernetes
- fine-tuning
- autonomous application submission
- unrestricted agent-to-agent debate
- unlimited revision loops
- a separate external vector DB
- automatic rule self-modification
unless a later spec explicitly requires it.

## Definition of success

A real application can be handled end-to-end:
JD → analysis → evidence → strategy → cover letter/resume → QA → submission snapshot,
with reproducible state, provenance, corrections, evals, and no manual re-prompting of the full procedure.


## Canonical workflow specifications

- `docs/05A_STATE_MACHINE_SPEC.md` controls runtime transitions and stale propagation.
- `docs/06A_WEB_RESEARCH_SPEC.md` controls company/job research and source separation.
- `IMPLEMENTATION_STATUS.json` controls Codex build-session resumption and must be updated after every milestone.


## v2.2 FINAL invariants

- OpportunityBrief is company/job-side only.
- EvidencePack maps candidate evidence to job outputs.
- ApplicationBrief owns candidate-specific gaps, selection risks, and assignment statement.
- Freeze/lock is not actual submission.
- `SUBMISSION_FROZEN → SUBMITTED` requires explicit confirmation.
- InterviewHandoff is separate from immutable SubmissionBundle.
- Production telemetry begins early.
- Build usable UI with each vertical slice.
