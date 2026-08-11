# Operating production

Everything an agent needs to connect to the running deployment, change it, and verify the
change. Written for someone who has never touched this host.

**No credential values appear in this file, and none may be added.** Secrets live in
`.env.prod` on the server (mode `600`, root-owned) and nowhere else. This document says
where each one is and how to set it without ever reading it. A repository is copied,
diffed, and pushed; a production secret pasted into one leaks the moment anybody clones it.

## The host

One small VPS runs several unrelated products side by side.

| | |
|---|---|
| SSH | `ssh sofi-prod` — the alias resolves host, user and key from `~/.ssh/config` |
| This product | `/opt/bot_globa` |
| Public URL | `https://predict.mypresence.ru` |
| Telegram bot | `@Numa_oracle_bot` |
| Resources | 4 GB RAM (~1.8 GB free), 59 GB disk (25% used) |

Neighbouring products under `/opt`: `sofi` (live), `foodtracker_ai_bot`, `predict`,
`telegram_bot`. **Only `sofi` and `bot_globa` are running.** Never modify another
product's compose project, database or environment.

### How traffic reaches this product

`sofi-proxy-1` is a Caddy container owning ports 80 and 443 for the whole host, including
TLS certificates. It is part of sofi's compose project — this product does not own it.

This stack publishes **no port**. It joins Caddy's external `web` network, and Caddy routes
the subdomain to the container by name:

```
predict.mypresence.ru {
	encode zstd gzip
	reverse_proxy bot_globa-api-1:8000
}
```

That block lives in `/opt/sofi/Caddyfile`. Members of the `web` network are exactly
`sofi-proxy-1` and `bot_globa-api-1`.

**If you ever edit the Caddyfile:** `caddy reload` silently does nothing here, because the
admin API is disabled. Use `docker restart sofi-proxy-1`, which drops sofi for a few
seconds. Confirm sofi recovered before walking away — see the verification section.

## Where each credential lives

All of them are already set. Every value was taken from another product on the same host;
none was invented.

| Setting | Source | Notes |
|---|---|---|
| `OPENAI_API_KEY` | `/opt/foodtracker_ai_bot/.env.prod` | sofi's key does not authenticate — use this one |
| `STRIPE_SECRET_KEY` | `/opt/sofi/.env.prod` | account-wide, deliberately shared |
| `STRIPE_WEBHOOK_SECRET` | this product's own Stripe endpoint | endpoint-scoped, **never** copy sofi's |
| `YOOKASSA_SHOP_ID`, `YOOKASSA_SECRET_KEY` | `/opt/sofi/.env.prod` | shop `1267385`, live |
| `TELEGRAM_BOT_TOKEN` | BotFather | belongs to `@Numa_oracle_bot` only |
| `CONTENT_ENCRYPTION_KEY` | generated for this deployment | **rotating it makes all stored user content unreadable** |

### Reading and writing settings without leaking them

A repository hook blocks any Bash command mentioning a `.env` file, deliberately: it keeps
secrets out of an agent's context, where they would end up in transcripts. Work with the
file through a script instead — the hook inspects the command, and the path lives in the
script rather than on the command line.

Write a helper locally, then feed it over stdin:

```bash
ssh sofi-prod 'python3 - ' < /path/to/local/script.py
```

A setter is already installed at `/root/set_env_value.py`. It takes the variable name as an
argument and the value on **stdin**, so nothing sensitive reaches a command line, a shell
history or a process listing, and it echoes back only a length and a short prefix:

```bash
printf '%s' 'the-value' | ssh sofi-prod "python3 /root/set_env_value.py SOME_SETTING"
```

To inspect settings, write a script that prints names, booleans and string *lengths* —
never values. Anything you print lands in the transcript permanently.

## Deploying

From a clean checkout of `main`, with `make check` and `make gates` already green locally:

```bash
DEPLOY_HOST=sofi-prod bash bot_globa/tools/deploy_prod_remote.sh
```

It syncs sources with `rsync --delete` (excluding `.env` and `.env.prod`, which are never
overwritten), rebuilds the images, and brings the stack up.

### The two failure modes you will hit

**1. `dependency failed to start: container bot_globa-api-1 is unhealthy`, and the logs
show a schema error.** The health check calls `/health/ready`, which requires the schema to
be current, but migrations have not run yet. Apply them, then bring the stack up:

```bash
cd /opt/bot_globa
docker compose -f docker-compose.prod.yml --env-file .env.prod \
  run --rm -T --no-deps --entrypoint alembic api upgrade head </dev/null
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d </dev/null
```

**2. A script delivered over `ssh 'bash -s'` stops halfway with no error.** `docker compose
run` and `exec` read stdin — which is the rest of your script. Every docker invocation in a
piped script needs `-T` and `</dev/null`. This looks like a hang or a silent success and
wastes a lot of time if you do not know it.

### A deploy that ships the old code

If the container behaves like the previous revision — for example raising an error that the
commit you are deploying deleted — compare the source on the host against the built image:

```bash
grep -c 'some_removed_symbol' /opt/bot_globa/app/config.py     # host source
docker run --rm --entrypoint sh bot_globa-api -c \
  "grep -c 'some_removed_symbol' /build/.venv/lib/python3.12/site-packages/app/config.py"
```

The cause was `uv` keying its built-wheel cache on distribution name and version: the
version rarely changes, so `uv sync` restored a stale `bot-globa` wheel even though the
`COPY app ./app` layer had correctly invalidated. The Dockerfile now passes
`--reinstall-package bot-globa`. If this reappears, that flag is the thing to check.

## Verifying

Run all of it after any change. Six checks must pass, the neighbour must still serve, and
the schema must be at head.

```bash
cd /opt/bot_globa
COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env.prod"

$COMPOSE ps --format '{{.Name}}\t{{.Status}}' </dev/null
$COMPOSE exec -T api python -m app.cli.verify_deployment </dev/null
$COMPOSE run --rm -T --no-deps --entrypoint alembic api current </dev/null

curl -s -o /dev/null -w 'live %{http_code}\n'  https://predict.mypresence.ru/health/live
curl -s -o /dev/null -w 'ready %{http_code}\n' https://predict.mypresence.ru/health/ready
curl -s -o /dev/null -w 'sofi %{http_code}\n'  https://mypresence.ru/healthz
```

Expected: six containers up with `api` healthy, six `[PASS]` lines, revision `(head)`,
three `200`s. An unsigned POST to `/webhooks/stripe` must return `401`.

To see the live commercial catalog exactly as the running process resolves it, ask the
process rather than reading config:

```python
from app.config import get_settings
from app.domain.billing import BillingCatalog

catalog = BillingCatalog(get_settings())
catalog.resolve_product_offer("reading_single", "INTERNATIONAL", "EUR")
```

## Release switches

All in `.env.prod`, all fail-closed. Flip one, then recreate the stack so every worker
picks it up.

| Switch | State | |
|---|---|---|
| `BILLING_ENABLED` | `true` | master switch |
| `YOOKASSA_ENABLED` | `true` | RU one-time payments |
| `YOOKASSA_RECURRING_ENABLED` | `false` | **blocked by the provider — see below** |
| `STRIPE_ENABLED` | `true` | EUR and USD |
| `SUBSCRIPTIONS_ENABLED` | `true` | Stripe only, in practice |
| `REFUNDS_ENABLED` | `false` | mechanism exists, 14-day window |
| `BILLING_KILL_SWITCH` | `false` | stops new checkout; does not block webhooks already in flight |
| `ORACLE_ROLLOUT_PERCENTAGE` | `100` | share of users who reach the oracle flow |

## Known limits

**Ruble subscriptions are impossible right now.** YooKassa answers a payment carrying
`save_payment_method` with:

```
HTTP 403 forbidden
This store can't make recurring payments. Contact the YooMoney manager to learn more
```

This is a permission on shop `1267385`, not a defect. The RU button is hidden while
`YOOKASSA_RECURRING_ENABLED` is `false`. When YooMoney enables autopayments, flip that one
switch. Do not look to the neighbouring product for a working example — it has no
autopayment code at all, so it proves only that the shop credentials work for one-off
charges.

To re-test the permission, create a 1 RUB payment with `save_payment_method: true` and
cancel it immediately. A rejected creation charges nothing and leaves no object.

**Nothing has ever been paid.** `payment_orders` is empty. Every money path is covered by
tests and by mocks, and no real Stripe checkout, signed webhook or subscription renewal has
ever run here. Treat the first real purchase as the actual acceptance test.

**Staging attestations are unrecorded.** The readiness gate requires `APP_ENV=staging` and
an `sk_test_`/`rk_test_` key, and refuses live credentials by design.

## Rules that are not negotiable

- **Never write a credential into the repository**, including in a doc like this one, a
  test fixture, or a commit message.
- **Never print a secret's value** into a transcript. Lengths and prefixes only.
- **Never rotate `CONTENT_ENCRYPTION_KEY`** without a re-encryption plan. Every stored
  reading, memory and birth profile becomes unreadable.
- **Never touch another product's** compose project, database, or `.env`. The one shared
  thing is Caddy, and editing it costs sofi a restart.
- **Never run `docker compose down -v`.** It destroys the database volume. A repository
  hook blocks it locally; nothing blocks it on the server.
- **Migrations are append-only.** Never edit an applied revision; add a new one.
- **Money paths are exactly-once.** Before claiming a billing change works, run
  `make gate-invariants` and `make test-postgres` — the concurrency tests need a real
  database, and a suite that skipped them proves nothing.

## Related documents

- [`enabling-stripe.md`](enabling-stripe.md) — the Stripe endpoint, its events, and the
  inline pricing model
- [`shared-host-deployment.md`](shared-host-deployment.md) — why this stack publishes no
  port and owns its own database
- [`production-readiness.md`](production-readiness.md) — the attestations and what they
  require
- `bot_globa/docs/platform-invariants.md` — the frozen behavior no change may weaken
