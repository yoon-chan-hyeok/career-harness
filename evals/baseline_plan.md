# Baseline / Ablation Plan

## Current phase

Do NOT delay implementation to manually build a large 30–50 case historical set.

Current historical cases are smoke-regression cases.

The primary short-term goal is to collect high-quality production telemetry from real use.

## Systems to compare later

B0: Strong LLM only  
B1: LLM + Career retrieval  
B2: Strategy + Writer  
B3: Full pipeline with QA and patch revision

## Production telemetry to collect now

At each stage:
- AI proposal,
- ACCEPT / EDIT / REJECT / SKIP,
- before/after when edited,
- artifact ids/versions,
- latency/cost.

For generated text:
- initial draft,
- final locked version,
- edit distance/diff,
- reviewer issues,
- accepted reviewer suggestions.

## Smoke regression now

Use the existing small set for critical failures:
- stale/incorrect profile fact,
- ownership overclaim,
- unsupported metric,
- claim-boundary violation,
- expression-store fact contamination,
- similar canonical errors.

## When to run real ablation

After enough real application/correction data accumulates,
export production telemetry into historical eval cases and compare B0/B1/B2/B3.

Do not infer component value from application outcome alone.
