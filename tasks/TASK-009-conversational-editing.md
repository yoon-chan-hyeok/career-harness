# TASK-009 — Conversational Artifact Editing + State Enforcement

Read `docs/05A_STATE_MACHINE_SPEC.md`.

## Implement command interpreter

Support at minimum:
- ㄱㄱ
- 이걸로 가자
- 잠가
- 다시
- 이건 Adjacent
- RAG 빼
- 이건 내가 한 거 아님
- 이 수치 틀림

## Requirements

- command produces a structured action,
- action validates allowed transition against current state,
- patch creates artifact/source version where required,
- locked artifact edits create a new version,
- downstream dependencies become STALE,
- stale/invalid artifacts cannot be final-locked,
- `ㄱㄱ` performs exactly one next valid workflow action,
- command result reports patched/stale artifacts to user.

## Tests

- locked QuestionBrief edited → v2 + old superseded + draft stale,
- ownership correction stales affected claim/resume/cover-letter outputs,
- metric conflict blocks final lock,
- `ㄱㄱ` never skips required Guided-mode approval,
- `다시` regenerates current stage only,
- chat transcript is not used as the state source of truth.
