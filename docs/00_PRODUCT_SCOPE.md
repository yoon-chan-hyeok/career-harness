# Product Scope

## User problem

Today the user manually orchestrates GPT:
- "자소서 바로 쓰지 말고 JD부터 봐"
- "이건 내가 직접 한 거 아님"
- "RAG 있다고 RAG 개발자라고 하지 마"
- "문항 전체 역할을 먼저 나눠"
- "이 메시지 잠가"
- "채용담당자 관점에서 다시 봐"

Career Harness makes those instructions the default workflow.

## Core product layers

### 1. Career Truth Core
Canonical personal/project truth.

### 2. Opportunity Analyzer
Turns a job opportunity into actual work requirements and candidate fit/gaps.

### 3. Application Composer
Uses the same truth/strategy to produce:
- cover letters,
- resumes,
- interview handoff.

### 4. Learning & Eval
Learns only from attributable user corrections/outcomes and regression tests.

## Non-goal

This is not primarily:
- a chat clone,
- a free-form multi-agent demo,
- a generic resume template site,
- an automatic applicant bot.

## Core success criterion

The user can say:

> "이 공고 지원할래."

and does not have to restate the entire writing/review methodology.

The system automatically performs the workflow, surfacing only high-value decisions or conflicts.
