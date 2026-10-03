# TASK-003 — Private Corpus Import

## Goal

Import whatever private career sources are currently available while keeping the service runnable when folders are incomplete.

Read `private_input/README.md`.

## v0.1 supported formats

Required:
- JSON
- JSONL
- TXT
- Markdown

Optional adapter later:
- DOCX
- PDF

## Sources

Recursively scan:
- `private_input/genesis/`
- `private_input/master_resume/`
- `private_input/project_records/**`
- `private_input/final_applications/`
- `private_input/corrections/`

## Implement

- idempotent source registration by path + content hash,
- source provenance,
- parser registry by file type/source category,
- conflict report,
- canonical snapshot generation,
- import summary,
- no-op behavior for empty folders.

Truth policy:
- project/master source may support canonical fact,
- final applications primarily support expression/history,
- old application facts cannot silently override stronger sources.

## Tests

- repeated import does not duplicate,
- empty optional directories do not fail startup/import,
- explicit canonical correction wins old application text,
- project metric provenance is retained,
- unconfirmed application submission is not marked submitted,
- private files are not required by CI.
