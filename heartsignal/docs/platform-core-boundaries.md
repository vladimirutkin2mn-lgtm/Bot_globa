# Platform core boundaries

This document defines which parts of the imported HeartSignal baseline are reusable platform infrastructure and which parts remain legacy relationship-domain behavior during the migration to Bot Globa.

## Purpose of this stage

ORA-002 changes product and repository identity without changing billing, privacy, database or user-flow behavior. The current relationship analysis remains operational until the new `Reading` domain is introduced in a separate pull request.

## Reusable platform core

The following areas are domain-neutral and must be preserved behind stable interfaces:

- FastAPI and Telegram transports;
- PostgreSQL sessions, Alembic execution and schema-health checks;
- encrypted private-content storage and deletion workflows;
- credit ledger and exactly-once entitlement consumption;
- one-time payments, subscriptions, refunds and reconciliation;
- durable Telegram updates, workers and retry semantics;
- analytics transport, correlation IDs and privacy-safe observability;
- LLM provider abstraction, strict structured-output validation and repair retry;
- release gates, deployment verification and kill-switch controls.

New oracle domains may call these capabilities but must not embed their own copies of financial, privacy or delivery logic.

## Legacy domain to replace later

The following code is still valid baseline behavior but is not part of the future generic core:

- conversation parser and two-participant constraints;
- relationship-stage intake;
- `Analysis` domain language and relationship report schema;
- message-evidence references;
- suggested relationship replies;
- relationship-specific prompts and Telegram texts;
- product SKU names beginning with `analysis_`.

These elements must be replaced incrementally after characterization tests protect the platform invariants.

## Identity rules

Runtime and packaging identity is centralized in `app.platform.identity`.

- `Bot Globa` is the repository/runtime identity.
- `Персональный AI-оракул` is the current working product description, not a permanent consumer brand.
- `HeartSignal` is retained only as the name of the imported baseline and in historical documentation or migration provenance.
- Database names, old Alembic revision identifiers, ledger keys and provider idempotency keys are not renamed in place.

## Dependency direction

```text
Telegram / API
      │
      ▼
Future oracle domains: Reading, Persona, Memory, Symbolic, Astrology
      │
      ▼
Platform services: LLM, billing, privacy, jobs, analytics, delivery
      │
      ▼
Providers and PostgreSQL
```

Platform modules must not import future persona-specific code. Domain modules may depend on platform interfaces, never directly on Stripe, YooKassa, OpenAI SDK details or Telegram transport objects.

## Protected invariants

Any future refactor must keep the following tests green:

1. exactly-once credit spend and entitlement delivery;
2. idempotent webhook and worker replay;
3. refund and subscription reconciliation;
4. encryption round-trip and absence of plaintext sensitive content;
5. complete privacy deletion without deleting immutable financial audit records;
6. migration upgrade/downgrade/upgrade;
7. release-readiness evidence tied to the deployed commit;
8. replay of completed results without a second LLM call or charge.

## Next implementation step

After this identity/boundary pull request, ORA-003 adds explicit characterization tests for the protected platform invariants. Only after those tests are merged should the new `Reading` domain and Tarot vertical slice replace relationship-specific behavior.
