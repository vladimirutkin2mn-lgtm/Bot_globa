# Deploying onto the shared host

The target host already serves other products behind a single Caddy instance. This
runbook describes joining it without disturbing them.

Prerequisites and the full go-live checklist are in
[`production-readiness.md`](production-readiness.md). This document is only about getting
the process running.

## Topology

```
                    ┌───────────── Caddy (owns :80/:443 and TLS) ─────────────┐
  predict.…  ──────▶│  reverse_proxy bot-globa-api:8000                        │
  other hosts ─────▶│  reverse_proxy <existing products>                       │
                    └──────────────────────┬──────────────────────────────────┘
                                    docker network `web` (external)
                                           │
        ┌──────────────────────────────────┴───────────────────────────────┐
        │ bot_globa stack: api · 5 workers · its own postgres              │
        └──────────────────────────────────────────────────────────────────┘
```

Caddy already runs on an external network named `web`, which is what makes a second
product possible at all. This stack joins that network and **publishes no port**, so it
cannot collide with anything already listening on the host. Its database is its own — it
does not share the other products' PostgreSQL.

The deployment tooling treats `web` as proxy-owned infrastructure and fails closed when
that network is absent. It must never create a replacement `web` network on behalf of the
proxy stack, because that can produce a healthy isolated application that Caddy cannot
reach.

## The one change outside this repository

Caddy owns TLS and routing, so the route has to be declared in its config, which lives
with the product that runs the proxy:

```diff
 predict.mypresence.ru {
 	encode zstd gzip
-	reverse_proxy predict-api:8080
+	reverse_proxy bot-globa-api:8000
 }
```

That subdomain currently points at a service that does not exist in the proxy owner's
compose file, so the documented state is 502 until the route is repointed. Nothing is
taken away by repointing it.

`bot-globa-api` must also be a resolvable alias for the API container on the shared
`web` network before Caddy is changed. Do not repoint Caddy to an unverified Docker DNS
name.

This is the only edit outside this repository. No application code of the other products
is touched.

## Deploying

```bash
export DEPLOY_HOST=root@<host>
export DEPLOY_PATH=/opt/bot_globa

make deploy-prod-remote      # sync, build, migrate under an advisory lock, smoke
make smoke-prod-remote       # verify an already deployed release
```

For the **first Oracle deployment**, keep rollout at zero and require a real public-route
smoke in the same operation:

```bash
REQUIRE_ORACLE_ROLLOUT_ZERO=1 \
PUBLIC_ORACLE_URL=https://predict.mypresence.ru \
make deploy-prod-remote
```

The guarded deploy refuses to continue when the proxy-owned `web` network is missing or
when `ORACLE_ROLLOUT_PERCENTAGE=0` is not present in the server-side `.env.prod`. When
`PUBLIC_ORACLE_URL` is set, smoke verifies `/health/live` and `/health/ready` through the
public HTTPS URL after the internal container checks and deployment verification pass.
This catches DNS, TLS, Caddy and upstream-routing failures that an internal health probe
cannot see.

To repeat only the public + internal smoke after a routing change:

```bash
PUBLIC_ORACLE_URL=https://predict.mypresence.ru make smoke-prod-remote
```

`.env.prod` lives only on the server. The sync excludes it explicitly, and the deploy
refuses to continue if it is missing. Start from
[`.env.prod.example`](../../bot_globa/.env.prod.example).

Migrations run through `app.cli.release`, which takes a PostgreSQL advisory lock, so two
concurrent deploys cannot race the schema.

## Billing is all-or-nothing at boot

With `APP_ENV=production`, enabling billing without a complete provider configuration is
a startup failure, not a degraded mode. The settings refuse:

- the `mock` provider;
- billing with neither Stripe nor YooKassa enabled;
- YooKassa without a shop id, secret key and webhook IP allowlist;
- a non-HTTPS `PAYMENT_PUBLIC_BASE_URL`.

So there are exactly two working shapes for a first deploy. Either fill the provider
credentials and ship with billing on, or set `BILLING_ENABLED=false` and ship the oracle
without payments — all four personas, readings, memory and follow-ups work either way.
There is no half-configured middle.

Set `ORACLE_ROLLOUT_PERCENTAGE=0` for the first deploy and raise it once the process is
observed healthy. `ORACLE_ENABLED=false` plus a restart is the emergency stop.

## Database: its own instance

This stack runs PostgreSQL 17, the version CI tests against. The host's other product
runs PostgreSQL 16, so reusing its instance would put production on a major version this
test suite has never executed against — and one restart would take both products down.

To reuse it anyway: point `DATABASE_URL` at that service, create the database and role
there, and delete the `db` service and the `pgdata` volume from
`docker-compose.prod.yml`. Advisory locks are per-database, so the release lock stays
isolated either way.

## Sharing one payment provider account with another product

The provider fans every subscribed event out to **every** endpoint configured on the
account, so both products receive each other's events. Two things keep them apart:

1. **A separate webhook endpoint** for this service, with its own signing secret, pointed
   at `https://<host>/webhooks/stripe`. Dashboard configuration, no code.
2. **A product marker.** Every checkout and subscription this service creates carries
   `metadata.product = bot_globa`. The webhook drops a checkout that does not carry it
   before the event reaches the durable inbox.

Invoice and subscription payloads are treated differently on purpose: the marker lives on
the subscription rather than on the object the provider sends, so those are rejected only
when the payload names a *different* product. Dropping them on a missing marker would
discard real renewals. Anything that still slips through resolves to `order_not_found`,
which is terminal and writes nothing to the ledger.

**What this does not fix.** The other product's endpoint still receives this service's
events. If its handler logs unknown orders at error level, this service's payments will
appear in its error log. That is cosmetic, not a correctness problem, but it will affect
alerting — decide whether to filter on that side or accept the noise.
