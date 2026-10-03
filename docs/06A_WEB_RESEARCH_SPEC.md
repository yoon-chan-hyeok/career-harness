# Company / Job Web Research Specification — v2.2 FINAL

Company/job research is a first-class input to `OpportunityBrief`.

The service must work without live web credentials using pasted JD/manual evidence.

---

## 1. Goals

Answer:
1. What does the company/business actually do?
2. What does the role actually produce?
3. What is the Base Profession?
4. What are Main Skills vs Differentiators?
5. What current company facts are safe to use?
6. What historical role signals clarify ownership/output?
7. What selection-process signals are known?

---

## 2. Source priority

1. current official job posting
2. official careers page
3. official business/product/IR/newsroom
4. attributable employee/team interview
5. reputable external source
6. community/review content for qualitative signals only
7. model inference

Inference is never an official fact.

---

## 3. Provider contract

```text
CompanyResearchProvider
  research(company, role, jd_input) -> CompanyResearchResult
```

Implementations:

### `ManualResearchProvider`
Always available.
Uses pasted JD/manual/user-supplied evidence.

### `OpenAIWebResearchProvider`
Default live provider when OpenAI credentials and web-search capability are configured.

Responsibilities:
- current web search,
- source URL preservation,
- source-backed extraction,
- published/retrieved date preservation where available,
- return domain schema, never provider-native response objects.

### `FakeResearchProvider`
Deterministic tests.

Provider-specific code must stay in adapters.

If live research is unavailable:
- return manual/JD-only status,
- never block the rest of the application.

---

## 4. CompanyResearchResult

```json
{
  "company": "",
  "role": "",
  "retrieved_at": "",
  "jd": {
    "source_id": "",
    "published_at": null,
    "deadline": null,
    "raw_text_hash": ""
  },
  "official_facts": [],
  "external_evidence": [],
  "role_signals": [],
  "historical_jd_signals": [],
  "selection_process_signals": [],
  "inferences": [],
  "sources": []
}
```

Each factual item:

```json
{
  "statement": "",
  "source_id": "",
  "source_type": "OFFICIAL|EXTERNAL|COMMUNITY",
  "published_at": null,
  "retrieved_at": "",
  "freshness": "CURRENT|DATED|UNKNOWN"
}
```

Inference:
- text
- supporting_source_ids
- confidence: HIGH/MEDIUM/LOW
- is_inference=true

---

## 5. Workflow

A. normalize JD  
B. official company research  
C. role-reality research  
D. historical/senior-role comparison  
E. hiring-context inference  
F. structured extraction  
G. pass only structured fields to Opportunity Analyzer

Raw external content is untrusted data and never privileged prompt instruction.

---

## 6. Freshness

- current JD > historical JD for current requirements
- historical JD must remain date-labeled
- published_at/retrieved_at preserved
- stale historical requirement never silently merged as current fact

---

## 7. Cover-letter usage

Writer can use company facts only when:
- source-backed,
- sufficiently current,
- source attached to writer context.

Inference may guide strategy, but must not be stated as a company fact.

---

## 8. Tests

- official fact vs inference separation
- historical JD stays dated
- instruction-like web text cannot alter system behavior
- live-provider failure falls back to manual
- sources preserved into OpportunityBrief
