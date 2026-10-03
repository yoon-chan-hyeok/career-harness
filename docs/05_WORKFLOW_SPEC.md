# Workflow Specification

## Top-level flow

```text
Opportunity created
→ Opportunity analysis
→ Evidence mapping
→ Application strategy
→ user strategy approval when needed
→ cover letter and/or resume composition
→ QA
→ minimal patch revision
→ submission snapshot
→ interview handoff
→ outcome/postmortem later
```

## Guided vs Fast mode

### Guided
Always surface:
- ApplicationBrief approval
- QuestionBrief approval

### Fast
Auto-continue when:
- no fact conflict,
- no fatal ambiguity,
- evidence coverage is strong,
- no user correction pending.

Escalate to user when:
- source conflict,
- NO_EVIDENCE on essential output,
- ambiguous ownership,
- high-risk claim,
- competing positioning.

## Conversational command semantics

- `ㄱㄱ` → execute the workflow's next valid action.
- `이걸로 가자` → approve current proposed artifact.
- `잠가` → lock current artifact version.
- `다시` → regenerate current stage; downstream becomes stale.
- `이건 Adjacent` → patch evidence classification.
- `RAG 빼` → remove evidence from current brief.
- `이건 내가 한 거 아님` → patch ownership; stale dependents.
- `이 수치 틀림` → invalidate/verify metric; stale dependents.

## Parallel QA

After a draft:
- Hard validator
- Claim grounding / ownership review
- Tired recruiter review

run in parallel where possible.

Reverse Interview is conditional:
- strong technical claim,
- ownership ambiguity,
- reviewer flags,
- interview-risk claim.

## Revision

Use issue-based patch revision.
Do not rewrite the entire draft unless structure is fundamentally wrong.

Support protected spans for user-approved text.

Automatic revision limit: 2.
