# Deployment & Observability

## Local

Docker Compose:
- backend
- frontend
- postgres/pgvector

## Production-like deployment

Use:
- managed PostgreSQL
- managed container/app service
- object storage only if raw docs needed
- HTTPS
- secret manager

No Kubernetes required.

## Required telemetry

Per run:
- stage
- prompt/model/provider
- input artifact ids
- output artifact id
- token usage
- estimated cost
- latency
- retry
- error
- user acceptance/rejection when applicable

## Health

- DB health
- migration state
- LLM provider health
- optional Jev provider health
- retrieval health

## Failure states

- RETRYABLE
- PROVIDER_UNAVAILABLE
- PARTIAL_COMPLETE
- NEED_USER_ACTION

A provider outage must not corrupt application state.

## CI

GitHub Actions:
- backend lint/type/test
- migrations check
- frontend lint/type/build
- unit + selected integration
- no private_input committed
