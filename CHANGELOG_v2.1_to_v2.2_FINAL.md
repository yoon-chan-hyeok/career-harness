# v2.1 → v2.2 FINAL

## P0 fixes

1. Reordered implementation:
   - M0 = repository/bootstrap
   - M1 = smoke regression + telemetry

2. Removed circular responsibility:
   - OpportunityBrief now company/job-side only
   - ApplicationBrief now owns fatal gaps, selection risks, assignment statement

3. Submission semantics:
   - READY_TO_FREEZE
   - SUBMISSION_FROZEN
   - explicit SUBMITTED event

4. InterviewHandoff separated from immutable SubmissionBundle.

5. Web research:
   - `OpenAIWebResearchProvider` defined as default live adapter
   - manual/fake fallbacks retained

6. Production telemetry:
   - `ArtifactFeedbackEvent`
   - `DocumentRevisionEvent`
   - DB schema/indexes added

7. UI moved earlier:
   - minimal Workbench shell at bootstrap
   - opportunity/question/resume UI with vertical slices
   - M14 reserved for hardening/polish

## P1 fixes

- CapabilityRecord uses STRONG/MODERATE/LIMITED/NONE, not pseudo-precise numeric confidence
- Resume v0.1 outputs structured content + Markdown + HTML preview
- API distinguishes freeze vs submit and recommends idempotency on costly mutation endpoints
- Domain model explicitly defines ExpressionRecord, CapabilityRecord, CompanyResearchResult, telemetry entities

## Final scope decision

No further pre-implementation feature expansion.
New features after this point should be driven by real usage/change requests.
