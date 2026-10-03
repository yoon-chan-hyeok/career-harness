# TASK-002 — Career Truth Core

Implement domain/repositories/services for:
Source, CareerFact, Project, Evidence, DecisionEpisode, Metric, Ownership, ClaimBoundary, WritingRule.

Implement:
- verification states
- fact-type truth policies
- source provenance
- version/supersede behavior

Tests:
- profile correction wins old profile text
- raw metric beats remembered metric
- project claim boundary returned
- ownership is not silently upgraded
- user isolation
