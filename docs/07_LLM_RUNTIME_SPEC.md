# LLM Runtime Specification

## Provider interfaces

### LLMProvider
Methods:
- `structured(prompt_id, context, schema)`
- `generate(prompt_id, context)`
- `embed(texts)`

### DecisionModel
Methods:
- `choose(task_id, state, options)`
- `score(task_id, state, scale)`
- `binary(task_id, state)`

Implement:
- OpenAI LLM provider
- Fake provider for tests
- LLM structured decision provider
- Jev shadow provider later

## LLM responsibilities

Use strong generative LLM for:
- Job Reality
- Application Strategy
- Claim/QuestionBrief
- Writer
- Reverse Interview
- detailed Recruiter Red Team
- Postmortem hypothesis drafting

Use smaller/cheaper model where acceptable:
- extraction
- simple question type
- style projection
- low-risk classification
- summarization

## Role information boundaries

### Strategist
Can see:
- OpportunityBrief
- EvidencePack
- relevant rules

### Writer
Can see:
- ApplicationBrief
- QuestionBrief
- selected evidence
- claim boundaries
- style projection

Cannot search arbitrary private data during generation.

### Tired Recruiter
Can see only:
- JD
- question
- draft

Goal:
- simulate fast external reader,
- identify rejection risks and unclear value,
- not fact-check hidden evidence.

### Fact Reviewer
Can see:
- atomic claims
- evidence
- metrics
- ownership
- sources

### Reverse Interviewer
Can see:
- draft claims
- detailed project records
- role context

## Prompt output discipline

Every analysis step should return Pydantic-validated structured output.

Free-form prose is reserved for:
- user-facing explanation,
- document generation,
- detailed reviewer comments.

## Trace

Every provider call logs:
- prompt version
- model/provider
- artifact inputs
- output artifact
- token/cost/latency
- retry/failure
