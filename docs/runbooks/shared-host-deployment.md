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
        │ bot_globa stack: api · 4 workers · its own postgres              │
        └──────────────────────────────────────────────────────────────────┘
```

Caddy already runs on an external network named `web`, which is what makes a second
product possible at all. This stack joins that network and **publishes no port**, so it
cannot collide with anything already listening on the host. Its database is its own — it
does not share the other products' PostgreSQL.

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
compose file, so it answers 502 today. Nothing is taken away by repointing it.

This is the only edit outside this repository. No application code of the other products
is touched.

## Deploying

```bash
export DEPLOY_HOST=root@<host>
export DEPLOY_PATH=/opt/bot_globa

make deploy-prod-remote      # sync, build, migrate under an advisory lock, smoke
make smoke-prod-remote       # verify an already deployed release
```

`.env.prod` lives only on the server. The sync excludes it explicitly, and the deploy
refuses to continue if it is missing. Start from
[`.env.prod.example`](../../bot_globa/.env.prod.example).

Migrations run through `app.cli.release`, which takes a PostgreSQL advisory lock, so two
concurrent deploys cannot race the schema.

## First deployment: billing stays off

Deploy with `BILLING_ENABLED=false`. The four oracle personas work, readings generate,
memory and follow-ups work — nothing charges. Payments are switched on only after the
five staging attestations pass, which is a separate exercise described in the readiness
runbook.

Set `ORACLE_ROLLOUT_PERCENTAGE=0` for the first deploy and raise it once the process is
observed healthy. `ORACLE_ENABLED=false` plus a restart is the emergency stop.

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
