# UI / State Specification — v2.2 FINAL

Main product is a Workbench, not chat-first.

UI is developed progressively with each vertical slice, not postponed to the final milestone.

## Navigation

1. Opportunities
2. Application Workspace
3. Career Truth
4. Eval/History
5. Settings

## Application Workspace stages

### Fit / Job / Evidence
Built with Opportunity Analyzer milestone.
- actual outputs
- sources
- base profession
- main skill/differentiator
- evidence mapping
- gaps become visible once ApplicationBrief exists

### Strategy
Built with first cover-letter slice.
- assignment statement
- positioning
- question portfolio
- approve/edit

### Questions
- intent
- primary message
- supporting claims
- evidence
- draft/editor
- protected text
- review issues

### Resume
- project order
- bullet candidates
- section budget
- Markdown/HTML preview
- skimmability review

### Review
- ClaimLedger
- fact/ownership
- recruiter risks
- conditional reverse interview
- portfolio QA

### Submission
- READY_TO_FREEZE
- freeze button/action
- frozen bundle
- explicit "submitted" confirmation
- submitted_at display

Never label a frozen draft as "submitted".

### Interview
Separate handoff generated from SubmissionBundle.

### Outcome
- stage/result
- postmortem hypotheses
- corrections/rule candidates

## Assistant side panel

Natural language edits current structured artifacts.
Display what state/artifact changed.

## Stale UI

Clearly mark stale downstream content.
Never silently display stale content as current.

## M14 scope

M14 is for:
- polish
- auth
- MCP
- privacy/delete UX
- deployment hardening

Core workbench screens should already exist before M14.
