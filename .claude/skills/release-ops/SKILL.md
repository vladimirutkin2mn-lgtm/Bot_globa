---
name: release-ops
description: Release and production operations — limited-release flags, rollout percentage, kill switches, spend caps, staging release-gate attestations, deployment topology and rollback. Use when the user says deploy, ship, release, rollout, kill switch, "turn the oracle off", "is it safe to launch", incident, or rollback.
---

# Release ops

Two independent control planes. Do not mix them: an oracle incident must not disable
billing, and a billing incident must not silently keep generating readings.

## 1. Oracle limited release (`docs/runbooks/oracle-limited-release.md`)

Read at **process startup** — changing an env var without replacing the running processes
does nothing.

| Variable | Purpose |
|---|---|
| `ORACLE_ENABLED` | global admission switch |
| `ORACLE_ROLLOUT_PERCENTAGE` / `ORACLE_ROLLOUT_SEED` | deterministic cohort; keep the seed stable while moving the percentage |
| `ORACLE_DISABLED_PERSONAS` | e.g. `astrologer,love_oracle` |
| `ORACLE_DISABLED_ENGINES` | e.g. `astrology-calculation-v1` |
| `ORACLE_GENERATION_RATE_LIMIT` / `..._WINDOW_SECONDS` | new readings per user; `0` = off |
| `ORACLE_DAILY_SPEND_CAP_MICROUSD` | conservative UTC-day cap; `0` = off |
| `ORACLE_MAX_RESERVED_COST_MICROUSD_PER_READING` | worst case incl. one repair call |

**Prefer the narrowest switch that contains the incident**: persona → `DISABLED_PERSONAS`;
astrology calculation → `DISABLED_ENGINES`; cost → lower rollout / set spend cap;
burst abuse → rate limit; only a general incident → `ORACLE_ENABLED=false`.

Rollback order: set the switch → restart **every** process that accepts Telegram oracle
traffic → confirm no new `readings` rows after the new processes are ready → leave billing,
refunds, subscriptions, webhooks and reconciliation untouched → review aggregate quality and
billing health before restoring traffic.

Rollout progression: `0 → 1 → 5 → 10 → 25 → 50 → 100`, advancing only on acceptable safety,
generation quality, provider failure and billing health. Changing the seed reshuffles the
cohort — that is a new experiment, not a continuation.

Spend-cap caveat: reservations are counted at reading creation and are **not** released when
a reading later fails or is deleted; the counter resets at 00:00 UTC. If pricing, token
bounds or repair policy change, update the reservation *before* raising rollout.

## 2. Staging release gates (`heartsignal/docs/release-gates.md`)

A limited-production snapshot requires the latest result of all five gates to be `passed`:
`stripe_subscription_sandbox`, `yookassa_subscription_sandbox`, `stripe_refund_sandbox`,
`yookassa_refund_sandbox`, `openai_followup_staging`.

Attestations are append-only and valid only for the exact tuple
(staging env, `RELEASE_CODE_SHA`, current Alembic revision, `RELEASE_CHECKLIST_VERSION`).
A new deploy, migration or checklist version makes a previous pass **stale**. CI and
fake-provider tests are not live acceptance evidence. Endpoints:
`GET /admin/release-readiness`, `POST /admin/release-gates/{gate_name}` (admin token).

Local check: `make verify-deployment` (`app.cli.verify_deployment`).

## 3. Deployment topology (`heartsignal/docs/deployment-render.md`)

One API + three private workers + managed PostgreSQL (`telegram-worker` under the `webhook`
profile locally). Pre-deploy runs `python -m app.cli.release`, which takes a PostgreSQL
advisory lock and upgrades Alembic to head before new processes start.

Telegram ingress is **at-least-once**: the API encrypts the update into
`telegram_update_inbox` keyed on `update_id`, commits, then returns `204`. Workers claim with
`FOR UPDATE SKIP LOCKED` under a lease; same-user updates stay ordered, different users run
concurrently. Therefore every business transition, payment op and ledger write must be
idempotent, and a repeated outbound message after a crash is an accepted boundary.

> **Known gap:** `docs/deployment-render.md` references a repository-root `render.yaml` that
> was not carried over in the baseline extraction. Recreate it (or replace it with the chosen
> target platform) before the first production deploy.

## Secrets

`TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET` (≥32 chars, `[A-Za-z0-9_-]`),
`CONTENT_ENCRYPTION_KEY`, provider keys and `ADMIN_API_TOKEN` live only in the deployment
environment. Losing `CONTENT_ENCRYPTION_KEY` makes every encrypted report, pending update and
FSM row unreadable — back it up out of band. Never echo a `.env` (the Bash guard hook blocks
it) and never paste secrets into a PR description or a log.
