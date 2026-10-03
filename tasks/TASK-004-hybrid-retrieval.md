# TASK-004 — Hybrid Retrieval + Context Compiler

Implement:
- FTS
- pgvector embedding/search
- metadata/verification filters
- fact vs expression retrieval
- StyleProjection sanitization
- stage-specific Context Compiler

Tests:
- semantic query can retrieve relevant DecisionEpisode
- expression retrieval cannot override canonical fact
- writer context contains only selected evidence
