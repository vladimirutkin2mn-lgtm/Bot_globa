---
name: billing-invariants
description: Money paths in this repo — credits ledger, one-time purchases, subscriptions, refunds, checkout, provider webhooks (Stripe / YooKassa / mock), product catalog and entitlements. Use when debugging a payment that did not credit, adding or changing a SKU or provider, touching app/providers/payments, app/services/*payment*/*checkout*/*subscription*/*refund*/*credits*, or when the platform-invariants gate fails.
---

# Billing invariants

This baseline carries real production billing semantics. They are frozen by
`heartsignal/docs/platform-invariants.md` and enforced by `make gate-invariants`.
Treat them as laws, not as code you may refactor freely.

## The ledger

- Balance is **derived** from immutable `credit_transactions`. There is no mutable counter.
- A pending payment does not increase the balance. Only a completed provider event does.
- One paid artifact ⇒ at most one successful spend. Retrying a spend returns the existing
  outcome (idempotency key, e.g. `analysis_full_access:<analysis_id>`), never a second debit.
- Concurrent spends can never make a balance negative — the user row is locked.
- A refund reverses exactly one spend, exactly once (`refund:<spend_transaction_id>`).
- A refunded spend can never later grant full access.
- Unlock and refund are mutually exclusive under concurrency.
- Ownership is checked on spend, unlock and refund; another user's ID reveals nothing.
- Credits do not fractionalize and do not expire.

## Webhooks are the source of truth

- Provider webhook completes the payment; the checkout return page never grants anything.
- HMAC/signature verified with constant-time comparison; events outside
  `PAYMENT_WEBHOOK_MAX_AGE_SECONDS` are rejected; body size capped by
  `PAYMENT_WEBHOOK_MAX_BYTES`.
- Endpoints: `POST /payments/webhooks/{provider}` (generic/mock),
  `POST /webhooks/stripe`, `POST /webhooks/yookassa`.
- Replay of a delivered event must be a no-op. Delivery failure in Telegram is **not**
  grounds for a refund and must not create a second entitlement or debit.
- Stale/pending payments are resolved by `payment_reconciliation_service`, not by retrying
  a grant.

## Catalog and orders

- An order stores an **immutable label/price snapshot**. Replaying an unfinished old-version
  order must not reprice it against the current catalog.
- Historical SKU codes stay valid in ledger and provider snapshots after the public catalog
  changes. Never rewrite them.
- Server-side price wins; the client never supplies an amount.

## Fail-closed flags

Production billing is disabled by default and each rail is separately gated:
`BILLING_ENABLED`, `BILLING_KILL_SWITCH`, `YOOKASSA_ENABLED`, `STRIPE_ENABLED`,
`SUBSCRIPTIONS_ENABLED`, `REFUNDS_ENABLED`, `YOOKASSA_RECURRING_ENABLED`.
Turning one on is a deliberate release decision, not a convenience during development.

## Local work

Use `PAYMENT_PROVIDER=mock`. Mock checkout is at an opaque
`/payments/mock/checkout/{token}` and never touches real money or card data. For Stripe
tooling use a `sk_test_...` key only — the Bash guard hook blocks `sk_live_` in commands.

## Before claiming a money change works

```bash
make gate-invariants      # protected characterization suite
make test-postgres        # concurrency / race tests need a real DB
```

Changing an invariant requires: a deterministic regression test, its exact pytest node ID
added to `scripts/run_platform_invariants.sh`, and the documented behavior updated in
`heartsignal/docs/platform-invariants.md`. Weakening one requires an explicit architecture
decision in the PR description.

Deeper references: `heartsignal/docs/payment-state-machines.md`,
`payment-webhook-security.md`, `provider-refunds.md`, `subscription-lifecycle.md`,
`stripe-subscriptions.md`, `yookassa-recurring-subscriptions.md`,
`payment-operations-runbook.md`.
