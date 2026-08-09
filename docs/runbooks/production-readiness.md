# Production readiness

What must be true before the oracle serves real users and takes real money. Every item
here is enforced by code — the setting names, blocker codes and gate names are the ones
the application actually checks.

Related: [`oracle-limited-release.md`](oracle-limited-release.md) covers rollout and
rollback once you are live. This document covers getting to that point.

## 1. The product ships disabled

Every commercial and external capability defaults to off. A deployment that changes
nothing is a bot with a stubbed model, no payments and no analytics.

| Setting | Default | Production |
|---|---|---|
| `APP_ENV` | `local` | `production` |
| `LLM_PROVIDER` | `stub` | `openai` |
| `OPENAI_API_KEY` | empty | real key |
| `LLM_MODEL` | `stub` | the model you priced |
| `GEOCODING_PROVIDER` | `stub` | `opencage` only if you accept the privacy delta below |
| `BILLING_ENABLED` | `false` | `true` |
| `STRIPE_ENABLED` | `false` | `true` |
| `YOOKASSA_ENABLED` | `false` | `true` |
| `SUBSCRIPTIONS_ENABLED` | `false` | `true` |
| `REFUNDS_ENABLED` | `false` | `true` |
| `YOOKASSA_RECURRING_ENABLED` | `false` | `true` |
| `ANALYTICS_ENABLED` | `false` | `true` |
| `ANALYTICS_BACKEND` | `noop` | `postgres` |
| `ADMIN_METRICS_ENABLED` | `false` | `true` |
| `ADMIN_API_TOKEN` | empty | a real secret |
| `LLM_INPUT_COST_USD_PER_MILLION_TOKENS` | unset | set together with the output cost |
| `LLM_OUTPUT_COST_USD_PER_MILLION_TOKENS` | unset | set together with the input cost |

`Settings.validate_production_billing` fails closed when `APP_ENV=production`. It refuses
a weak or malformed `CONTENT_ENCRYPTION_KEY`, a non-HTTPS `PAYMENT_PUBLIC_BASE_URL`, the
`mock` payment provider, billing without an enabled provider, and an incomplete YooKassa
configuration. A half-configured production boot does not start.

### The geocoder is the only outbound user data

`GEOCODING_PROVIDER=opencage` sends the user's birth-place query to a third party. It is
the single piece of user text that leaves the service. `stub` resolves offline from a
bundled table and makes no network call. Switching is a deliberate privacy decision —
see [`privacy-deletion-retention.md`](../../bot_globa/docs/privacy-deletion-retention.md).

## 2. Five staging attestations

`GET /admin/release-readiness` (header `X-Admin-Token`) reports the snapshot. It is not
ready until all five gates are `passed`:

| Gate | Proves |
|---|---|
| `stripe_subscription_sandbox` | a Stripe subscription completes end to end |
| `yookassa_subscription_sandbox` | a YooKassa recurring subscription completes |
| `stripe_refund_sandbox` | a Stripe refund reaches the ledger exactly once |
| `yookassa_refund_sandbox` | a YooKassa refund reaches the ledger exactly once |
| `openai_followup_staging` | a paid follow-up runs against the real model |

**Attestations are recorded on staging, not production.** The snapshot refuses to
consider a gate unless `APP_ENV=staging`, the release commit SHA is a valid hex string
and the checklist version matches the expected pattern. It also records the Alembic
schema revision, so an attestation is bound to the exact schema it was taken against.

### What blocks each gate

Run the readiness endpoint and read the blocker codes; they map one to one onto
configuration:

| Blocker | Fix |
|---|---|
| `environment_not_staging` | attest on staging |
| `release_code_sha_invalid` | pass the real deployed commit SHA |
| `release_checklist_version_invalid` | pass a versioned checklist identifier |
| `schema_revision_missing` | run migrations before attesting |
| `billing_disabled`, `public_https_missing` | enable billing behind HTTPS |
| `stripe_disabled`, `stripe_test_credentials_required`, `stripe_webhook_secret_missing` | Stripe on, `sk_test_`/`rk_test_` key, webhook secret set |
| `stripe_subscription_offer_missing` | configure the Stripe subscription Price and its expected amount together |
| `yookassa_disabled`, `yookassa_test_credentials_missing`, `yookassa_webhook_allowlist_missing` | YooKassa on, test shop credentials, webhook IP allowlist |
| `subscriptions_disabled`, `yookassa_recurring_disabled` | enable the subscription paths |
| `refunds_disabled` | enable refunds |
| `openai_provider_required`, `openai_api_key_missing`, `openai_model_missing` | point the LLM at a real model |

Stripe and YooKassa credentials must be **test** credentials on staging. The check
rejects a live Stripe key outright.

## 3. Deployment

```bash
python -m app.cli.release      # advisory-locked `alembic upgrade head`
make health                    # /health/live + /health/ready
python -m app.cli.verify_deployment
```

`app.cli.release` takes a PostgreSQL advisory lock, so two concurrent deployments cannot
race the schema. `verify_deployment` checks API liveness and readiness, Telegram webhook
configuration and authentication, delivery errors and the update backlog.

Processes to run: the API (webhook ingress), the Telegram worker, the billing worker, the
maintenance worker and the oracle-memory worker. Telegram ingress is at-least-once, so
every worker must be idempotent — they are, but a fork must stay that way.

## 4. First traffic

Follow [`oracle-limited-release.md`](oracle-limited-release.md). In short: keep
`ORACLE_ROLLOUT_SEED` stable, advance `ORACLE_ROLLOUT_PERCENTAGE` through
`0 → 1 → 5 → 10 → 25 → 50 → 100`, and set `ORACLE_DAILY_SPEND_CAP_MICROUSD` and
`ORACLE_MAX_RESERVED_COST_MICROUSD_PER_READING` from the model you actually configured.
The cap reserves the worst case per admitted reading, so it must upper-bound one primary
generation plus the single allowed repair.

`ORACLE_ENABLED=false` plus a process restart is the emergency stop. It denies new
readings before any private content is persisted; billing, refunds and webhooks keep
running unless their own incident requires otherwise.

## 5. Known gaps

These are not configuration — they are outstanding work.

| Gap | Blocks launch? | Note |
|---|---|---|
| **No deployment manifest** | **Yes** | `deployment-render.md` describes a `render.yaml` that was never carried over. Pick a platform and write the manifest. |
| Staging environment with provider test keys | **Yes** | Without it none of the five attestations can be taken. |
| Legacy HeartSignal vertical still present | No | «Разобрать переписку» still appears in the main menu next to the four oracle personas. Removal touches the credit ledger and needs its own reviewed change. |
| Billing SKUs named `analysis_single` / `analysis_pack_5` | No | They sell credits that now unlock readings. Renaming them is a financial-identifier migration with immutable label snapshots — separate from removing the product. |

## 6. Definition of done before the first real payment

- [ ] `make ci` green on the release commit
- [ ] `make gates` green — billing, privacy, safety, release controls and quality
- [ ] Migrations applied via `app.cli.release`, schema revision recorded
- [ ] All five staging attestations `passed` against that exact commit and schema
- [ ] `verify_deployment` clean against the deployed environment
- [ ] Privacy deletion exercised end to end, including a birth profile
- [ ] `ORACLE_DAILY_SPEND_CAP_MICROUSD` set from measured cost, not guessed
- [ ] Rollback rehearsed: `ORACLE_ENABLED=false` plus restart, verified no new `readings` rows
