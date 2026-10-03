# TASK-006 — Cover Letter Single Question + UI

Inputs:
- OpportunityBrief
- EvidencePack

First create `ApplicationBrief`:
- Positioning
- Main Skill message
- Differentiator message
- Fatal gaps
- Selection risks
- Fatal gap strategy
- Assignment Statement
- do_not_position_as

Then implement one question vertical slice:
ApplicationBrief
→ QuestionBrief
→ optional claim approval
→ writer
→ ClaimLedger
→ hard QA
→ tired recruiter
→ conditional reverse interview
→ issue-based patch revision
→ final lock

Minimal UI:
- Strategy panel
- one question workbench
- claim approval/edit
- draft/review/issues
- protected text support

Acceptance:
- assignment statement requires EvidencePack
- writer cannot invent unsupported metric
- protected text survives patch revision
- ClaimLedger links factual claims to evidence
