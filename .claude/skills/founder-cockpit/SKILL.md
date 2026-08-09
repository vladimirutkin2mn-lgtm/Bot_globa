---
name: founder-cockpit
description: Founder-level work on this product — reading funnel and retention metrics, unit economics (LLM cost vs price), backlog prioritization against the MVP critical path, launch readiness, and turning a product idea into ORA tickets. Use when the user asks about metrics, conversion, pricing, margin, cost per reading, "what should we build next", "are we ready to launch", or wants a product decision rather than a code change.
---

# Founder cockpit

This is the product/business lane. It reads the same system the code lane writes, so answers
stay grounded in the actual schema and telemetry — never in invented numbers.

## Where the real numbers live

| Question | Source |
|---|---|
| Funnel, completion rate, purchases, failure categories, billing job/outbox health | `GET /admin/metrics` (`app/services/admin_metrics.py`) — aggregates only |
| LLM cost / latency / tokens by model, persona, prompt version | `app/observability/oracle_quality.py`, `oracle_product_analytics.py` |
| Product events (funnel, persona, intake, purchase, memory, follow-up, share, safety) | `app/providers/analytics_postgres.py`, strict allow-list |
| Catalog and prices | `app/domain/products.py` + `PRODUCT_*_PRICE_MINOR` env |
| Launch readiness | `GET /admin/release-readiness`, `make verify-deployment` |

Enable locally: `ANALYTICS_BACKEND=postgres`, `ADMIN_METRICS_ENABLED=true`,
`ADMIN_API_TOKEN=...`, then

```bash
curl --fail -H "X-Admin-Token: $ADMIN_API_TOKEN" http://localhost:8000/admin/metrics
```

Read-only SQL exploration of the local dev DB is available through the `postgres-dev` MCP
server (restricted access mode, local database only — never point it at production).

**Aggregates only.** Metrics never contain questions, readings, birth data, Telegram
identity or receipt contact. If a question cannot be answered from aggregates, the answer is
"we do not measure that yet" plus the event to add — not a peek at user content.

## Unit economics

Margin per reading = price − (LLM primary call + allowed repair call + downstream calls).
The cost side is already modelled conservatively for the release cap:
`ORACLE_MAX_RESERVED_COST_MICROUSD_PER_READING` must upper-bound worst-case generation
including one repair. Use that number as the pessimistic cost floor when pricing, and the
observed p50/p95 from quality observability as the realistic one.

Current catalog (fictional placeholder prices, RUB minor units — set real ones explicitly
before launch): `PRODUCT_ANALYSIS_SINGLE_PRICE_MINOR=19900`,
`PRODUCT_ANALYSIS_PACK_5_PRICE_MINOR=69900`,
`PRODUCT_SUBSCRIPTION_MONTHLY_PRICE_MINOR=99000` / `_CREDITS=30`.

A price change is a catalog migration, not an env tweak in isolation: existing orders keep
their immutable label/price snapshot (see `billing-invariants`).

## Prioritization

`docs/MVP_BACKLOG.md` defines P0/P1/P2 and the critical path:

`ORA-001 → ORA-003 → ORA-101…107 → ORA-201/202/204 → ORA-301/303/305 → ORA-401 → ORA-402 →
ORA-403 → ORA-404 → ORA-405 → ORA-601…605`

When asked "what next", answer from the critical path and the current state of the repo
(what is merged, what is still unchecked in the backlog) — not from what sounds exciting.
Anything off the critical path is P2 until the four personas ship end to end.

## Turning an idea into work

Produce a ticket in the backlog's own shape, not a prose brief:

```
### ORA-xxx · <name> — P0|P1|P2 / S|M|L
- [ ] concrete, checkable step
**Acceptance:** the observable condition that proves it works
```

Then check it against: does it need a new safety rule (`oracle-safety`), money path
(`billing-invariants`), stored user content (`privacy-encryption`), or schema
(`db-migrations`)? Each "yes" is part of the estimate, not a follow-up.

## Launch readiness (ORA-605)

Privacy deletion end-to-end incl. BirthProfile · purchase/refund/subscription sandbox paths ·
safety and astrology fixtures · readiness snapshot pinned to an exact commit.
All five staging gates `passed` and non-stale — see `release-ops`.
