# Truth, Retrieval, Context Compilation

## Truth is type-specific

Do not use one global source-priority list for every fact.

### Profile truth
1. latest explicit user confirmation/correction
2. official credential/document
3. trusted master profile
4. historical applications
5. old conversation inference

### Project metric truth
1. raw experiment/results source
2. locked project record
3. master resume/project summary
4. application text
5. conversational memory

### Ownership truth
1. explicit user confirmation
2. locked project ownership record
3. raw repository/history evidence
4. old application language
5. inference

### Company fact truth
1. current official company/job source
2. authoritative external evidence
3. inference

## Retrieval stores

### Fact retrieval
Search:
- Evidence
- DecisionEpisode
- Metric
- Ownership
- ClaimBoundary

### Expression retrieval
Search:
- accepted final answers,
- user corrections,
- tone patterns,
- argument structures.

Expression retrieval never supplies truth directly.

## Expression sanitization

Convert retrieved writing into `StyleProjection`:
- logic pattern
- tone
- preferred phrasing pattern
- avoid pattern

Strip/revalidate:
- company names
- dates
- metrics
- graduation/employment state
- role-specific facts

## Hybrid retrieval

Use PostgreSQL:
- FTS/BM25-like lexical
- pgvector semantic
- metadata filters

Candidate generation:
1. verification/status filter
2. lexical + semantic retrieval
3. task-specific metadata filter
4. reranking
5. truth resolution
6. context compilation

## Context Compiler

Never dump the whole DB into the LLM.

Compile stage-specific context:

### Opportunity analyzer
JD + company evidence + compact capability profile.

### Evidence mapper
actual outputs + top evidence candidates + ownership/boundary metadata.

### Writer
ApplicationBrief + QuestionBrief + selected evidence only + rules.

### Tired recruiter
JD + question + draft only.
Do NOT expose private evidence reasoning.

### Fact reviewer
draft claims + supporting evidence/metrics/ownership.

### Reverse interviewer
draft claims + deeper project facts.

## External content safety

Treat JD/web text as untrusted data.
Extract structured fields before downstream reasoning.
Do not let source-page instructions become system instructions.
