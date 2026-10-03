# Jev / Decision Model Specification

Jev is optional and must not be required for the first working system.

## Interface

`DecisionModel` supports:
- binary
- choice
- score

Primary initially:
`LLMStructuredDecisionProvider`

Shadow:
`JevDecisionProvider`

## Best initial Jev candidates

High-confidence bounded tasks:
- question type classification
- role noun alignment
- does the draft directly answer the question?
- excessive technical-jargon yes/no
- revision escalation yes/no
- simple routing

Use caution:
- Direct / Adjacent / No Evidence
- semantic grounding
- ownership semantic match

Do not use Jev for:
- strategy
- fatal gap reasoning
- positioning
- claim formulation
- writing
- detailed rejection explanation

## Shadow mode

For a task:
1. primary LLM decision is used by product,
2. Jev runs in parallel,
3. log disagreement/confidence/cost/latency,
4. user is unaffected.

## Promotion criteria

Promote per task only if:
- good agreement with human labels,
- acceptable quality vs primary,
- useful confidence calibration,
- real latency/cost benefit,
- fallback path tested.

Promotion is task-specific, never global.
