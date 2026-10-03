# private_input — Local Private Seed Data

This directory is intentionally gitignored except for this README and `.gitkeep`.

The application/importer must work even when some folders are empty.
Do not make all private corpora required for server startup.

Recommended structure:

```text
private_input/
├─ genesis/
│  ├─ career_agent_genesis_v2.jsonl
│  ├─ canonical_snapshot_v2.json
│  ├─ application_state_v2.json
│  └─ eval_cases_v2.jsonl
│
├─ master_resume/
│  └─ canonical master resume / structured export
│
├─ project_records/
│  ├─ rag/
│  ├─ mas/
│  ├─ face/
│  ├─ ocr/
│  └─ traffic/
│
├─ final_applications/
│  └─ company-specific locked/final application records
│
└─ corrections/
   └─ optional explicit correction exports
```

## v0.1 supported ingest formats

Required:
- `.json`
- `.jsonl`
- `.txt`
- `.md`

Optional/later adapter:
- `.docx`
- `.pdf`

Prefer text/markdown/structured exports for canonical ingest where available.

## Import rules

1. Import recursively from existing files only.
2. Preserve source path and content hash.
3. Re-import is idempotent.
4. Do not overwrite stronger canonical truth silently.
5. Conflicts produce a conflict report.
6. Master/project sources become `Source` records with provenance.
7. Final applications are expression/history sources, not canonical project truth.
8. Raw private files must never be committed to Git.

## Suggested next data additions

Before high-quality personal production use, add:
- canonical master resume,
- locked RAG/MAS/Face/OCR/Traffic records,
- representative final submitted applications.

The codebase must be implementable before these are all present.
