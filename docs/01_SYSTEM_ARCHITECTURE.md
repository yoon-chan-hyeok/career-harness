# System Architecture

## Architecture style

Modular monolith first.

```text
Next.js Workbench
      │
      ▼
FastAPI
├─ career_truth
├─ opportunity
├─ application
│  ├─ cover_letter
│  ├─ resume
│  └─ interview
├─ retrieval
├─ ai_runtime
├─ eval
└─ adapters
   ├─ mcp
   └─ external_research
      │
      ▼
PostgreSQL + pgvector
```

## External providers

```text
LLMProvider
├─ OpenAIProvider
└─ FakeLLMProvider

DecisionModel
├─ LLMStructuredDecisionProvider
├─ JevDecisionProvider (shadow initially)
└─ FakeDecisionProvider

CompanyResearchProvider
├─ WebResearchProvider
└─ FakeResearchProvider
```

Provider outages must not corrupt workflow state.

## Internal modules

### career_truth
Owns canonical data and truth policies.

### retrieval
Retrieves evidence/expression candidates; does not decide truth.

### opportunity
Converts JD/company evidence into `OpportunityBrief`.

### application
Creates `ApplicationBrief`, `QuestionBrief`, cover letters, resumes, submission bundles.

### ai_runtime
Prompt/version/model routing and structured outputs.

### eval
Regression/eval harness, telemetry, baseline comparison.

### adapters
REST, MCP, external provider adapters only.

## No microservices in v1

All modules share one application/database.
Boundaries are code/module boundaries, not network boundaries.
