# Bot Globa — application

The Telegram-first personalized AI oracle. Product scope lives at the repository root
(`../README.md`, `../docs/`); this file covers running and changing the code.

## Requirements

- Python 3.12
- [uv](https://docs.astral.sh/uv/) for dependency management
- Docker and Docker Compose for the full local stack

## Getting started

```bash
make install     # ./.venv from uv.lock — the exact versions CI uses
make db-up       # PostgreSQL only, for host-side development and tests
make db-upgrade  # alembic upgrade head
make check       # fmt-check + lint + strict mypy + tests — run before every push
```

`make help` lists every target. `make` works from the repository root too.

Dependencies are locked in `uv.lock`. After editing `pyproject.toml`, run `make lock` and
commit the result; CI fails if the lock file is stale.

## Running

```bash
make up      # full dev stack in Docker
make api     # API on the host with reload
make bot     # bot on the host with long polling
make health  # /health/live + /health/ready
```

Copying `.env.example` to `.env` verbatim breaks host-side `pytest`: the template leaves
several numeric variables empty and pydantic-settings treats an empty value as a parse
error where an absent one would fall back to its default. `make` strips empty assignments
when it generates `.env`; the template itself is still worth fixing.

## Testing

```bash
make test         # full suite (requires PostgreSQL)
make test-fast    # skip the PostgreSQL-backed tests
make coverage     # full suite plus a branch-coverage report for app/
make gates        # the five protected regression gates
make ci           # the whole CI pipeline, locally
```

Postgres-marked tests skip silently without `TEST_DATABASE_URL`, so a green run that
skipped them proves nothing. The Makefile always exports it and fails fast when the
database is unreachable. Dev and test databases are separate (`bot_globa` /
`bot_globa_test`), exactly as in CI.

## Architecture

Layered; dependencies flow one way, `bot`/`api` → `services` → `repositories`/`db` →
`domain`. The rules a linter cannot enforce are written down in
[`docs/style.md`](docs/style.md) — read it before adding a module.

| Layer | Path |
|---|---|
| Domain | `app/domain/` — pure rules, value objects, validators |
| Services | `app/services/` — use cases: readings, personas, memory, checkout, billing |
| Repositories | `app/repositories/` — data access, encrypted private content |
| DB | `app/db/` — SQLAlchemy models, FSM, Telegram inbox, billing, release gates |
| Bot | `app/bot/` — aiogram routers, keyboards, renderers, safety middleware |
| API | `app/api/` — `health`, `admin`, `payments`, `webhooks`, `telegram` |
| Providers | `app/providers/` — `llm/` and `payments/` behind interfaces |
| Prompts | `app/prompts/` — versioned persona prompt packs |
| Workers | `app/workers/` — billing, maintenance, oracle memory, Telegram |
| CLI | `app/cli/` — release, backfills, retention, verification |

HTTP surface: `POST /telegram/webhook`, `POST /payments/webhooks/{provider}`,
`POST /webhooks/stripe`, `POST /webhooks/yookassa`, `GET /health/{live,ready}`,
`GET /admin/metrics`, `GET /admin/release-readiness`.

Telegram ingress is at-least-once: the API encrypts the update into
`telegram_update_inbox` keyed on `update_id`, commits, then returns `204`; workers claim
rows with `FOR UPDATE SKIP LOCKED` under a lease. Every business transition, payment
operation and ledger write is therefore idempotent.

### Reading personas

Tarot, Love Oracle and Mystical Psychologist share one `PersonaReadingUseCase` and one
router factory; they differ only by the data in `app/bot/persona_flows.py` and
`app/domain/persona.py`. Adding one of those is a checklist in
[`docs/style.md`](docs/style.md), not a new vertical.

The astrologer keeps its own use case, router and renderer because it collects a consented
birth profile and runs a calculation engine. Its birth-place lookup is the only thing in
the product that sends user text to a third party — see
[`docs/privacy-deletion-retention.md`](docs/privacy-deletion-retention.md). The default
provider (`GEOCODING_PROVIDER=stub`) is offline and makes no network call.

### Paid follow-ups

Every full reading includes one follow-up question. The entitlement lives in
`reading_followups`, keyed on the reading rather than the persona, and the answer may
only cite sections that exist in the reading it explains. See
[`docs/style.md`](docs/style.md).

## Non-negotiable contracts

- **Safety** — classify input before it reaches a prompt, validate output before
  persistence; crisis stops the mystical flow entirely.
- **Money** — balance derives from immutable `credit_transactions`; the webhook is the
  source of truth; every grant, spend and refund happens exactly once.
- **Privacy** — sensitive content is encrypted at rest, memory and birth data are
  consent-gated, deletion purges content while immutable financial records survive.
- **Migrations** — applied revisions are immutable; add new ones.
- **LLM** — strict structured output, one controlled repair, versioned prompts; untrusted
  data is never merged into instructions.
- **Engines** — deterministic and versioned; an unknown birth time means no ascendant and
  no houses.

## Definition of done

See [`AGENTS.md`](AGENTS.md). In short: acceptance criteria pass, `make check` is green,
`make db-verify` passes when migrations changed, the compose config and production image
still build, errors have safe user-facing behavior, docs reflect the decision, and
`make gates` is green.

Report the actual command output. A gate is never made green by deleting a test node ID
or loosening an assertion.

## Reference documentation

| Topic | Document |
|---|---|
| Code style and layering | [`docs/style.md`](docs/style.md) |
| Layer boundaries | [`docs/platform-core-boundaries.md`](docs/platform-core-boundaries.md) |
| Frozen production behavior | [`docs/platform-invariants.md`](docs/platform-invariants.md) |
| Privacy, deletion, retention | [`docs/privacy-deletion-retention.md`](docs/privacy-deletion-retention.md) |
| Analytics and admin metrics | [`docs/analytics-admin-observability.md`](docs/analytics-admin-observability.md) |
| Payment state machines | [`docs/payment-state-machines.md`](docs/payment-state-machines.md) |
| Payment operations | [`docs/payment-operations-runbook.md`](docs/payment-operations-runbook.md) |
| Subscriptions | [`docs/subscription-lifecycle.md`](docs/subscription-lifecycle.md) |
| Refunds | [`docs/provider-refunds.md`](docs/provider-refunds.md) |
| Release gates and verification | [`docs/release-gates.md`](docs/release-gates.md) |
| **Production readiness** | [`../docs/runbooks/production-readiness.md`](../docs/runbooks/production-readiness.md) |
| Rollout and rollback | [`../docs/runbooks/oracle-limited-release.md`](../docs/runbooks/oracle-limited-release.md) |

`PRODUCT_SPEC.md` and `TASKS.md` describe the historical HeartSignal product. They are
kept for the invariants they explain and do not define current or future scope.
