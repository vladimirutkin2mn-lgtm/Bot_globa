# CLAUDE.md

Guidance for Claude Code in `Bot_globa`. Kept lean — it points at the detailed docs and
skills rather than duplicating them.

## What this is

**Bot_globa** — Telegram-first personalized AI oracle. The user picks a direction, asks a
question and gets an interactive reading. The product remembers earlier readings (with
explicit consent), links new answers to that history, and can produce safe shareable cards.

Four MVP directions: **tarot reader**, **love oracle**, **mystical psychologist**,
**horoscope / astrologer**.

Two deterministic engines sit outside the LLM: a **Symbolic Engine** draws tarot cards
(seeded from `reading_id`), and an **Astrology Calculation Engine** computes the natal chart.
The LLM only *explains* what those engines returned — it never invents cards, planets, houses
or an ascendant.

Entertainment and reflection, not fact: no prediction, no reading of another person's mind,
no diagnosis, no high-stakes advice. See the `oracle-safety` skill — it is the product, not a
disclaimer.

## Repository layout

```
Bot_globa/
├── docs/                 # oracle product plan — the authority for future scope
│   ├── FABRIC_BOT_ADAPTATION_PLAN.md
│   ├── MVP_SCOPE_V2.md
│   ├── MVP_BACKLOG.md            # the ORA-xxx ticket list + critical path
│   └── runbooks/oracle-limited-release.md
├── heartsignal/          # the application (imported HeartSignal production baseline)
│   ├── AGENTS.md         # migration rules + definition of done — read this
│   ├── app/  tests/  migrations/  scripts/  docs/
│   └── Makefile
└── Makefile              # thin wrapper: forwards every target into heartsignal/
```

The code lives in `heartsignal/`. `make` works from either directory.

## Sources of truth (read before changing behavior)

1. `heartsignal/AGENTS.md` — migration rules, safety rules, privacy defaults, definition of done
2. `docs/FABRIC_BOT_ADAPTATION_PLAN.md` — migration strategy
3. `docs/MVP_BACKLOG.md` — the ticket you are implementing and its acceptance criteria
4. `heartsignal/docs/platform-core-boundaries.md` — what may depend on what
5. `heartsignal/docs/platform-invariants.md` — frozen production behavior
6. existing code and tests
7. `heartsignal/PRODUCT_SPEC.md`, `heartsignal/TASKS.md` — **legacy only**, historical
   HeartSignal behavior

When documents conflict, the repository-level oracle plan wins over the legacy HeartSignal
docs. Do not reverse-engineer a flow from code when a doc describes it.

## Stack

Python **3.12**, FastAPI, aiogram 3, PostgreSQL (SQLAlchemy 2 async + Alembic), Pydantic 2,
`openai` SDK behind a provider-neutral `LLMClient`, `astronomy-engine` (pinned), Docker
Compose. Quality: `ruff` (E,F,I,UP,B,ASYNC,RUF), `mypy --strict`, `pytest`.
Dependencies via `pip install -e '.[dev]'` (`make install` creates `./.venv`).

No Redis: the Telegram queue, FSM and the outbox are all PostgreSQL-backed.

## Commands

```bash
make install        # ./.venv + project with dev extras
make check          # fmt-check + lint + type + test  ← before every push
make ci             # full local reproduction of the CI pipeline
make gates          # the five protected regression gates

make db-up          # postgres only (host-side dev, IDE, tests)
make db-upgrade     # alembic upgrade head
make db-verify      # upgrade -> downgrade -1 -> upgrade  (what CI checks)
make db-revision MSG="describe change"

make up / down / ps / logs / sh      # dev stack
make api / bot                       # run on the host
make health                          # /health/live + /health/ready
make help                            # every target
```

Postgres-marked tests **silently skip** without `TEST_DATABASE_URL`, so a green run that
skipped them proves nothing. The Makefile always exports it and fails fast when the database
is unreachable — `make test-fast` is the explicit way to run without one. Dev and test
databases are separate (`heartsignal` / `heartsignal_test`) exactly as in CI; `make db-verify`
and `make db-reset-test` only ever touch the test one.

## Architecture

Layered; dependencies flow domain → platform, never back. A platform module
(`app/platform/`, `app/providers/`, billing, privacy) must never import persona-specific code.
Runtime identity is centralized in `app.platform.identity`.

| Layer | Path | Contents |
|---|---|---|
| Domain | `app/domain/` | pure rules, value objects, validators (`reading`, `persona`, `tarot`, `natal_chart`, `oracle_safety`, `billing`) |
| Services | `app/services/` | use cases — reading generation, personas, memory, checkout, subscriptions, refunds, safety boundary |
| Repositories | `app/repositories/` | data access, private (encrypted) content |
| DB | `app/db/` | SQLAlchemy models, FSM, telegram inbox, billing, release gates |
| Bot | `app/bot/` | aiogram handlers, keyboards, states, renderers, safety middleware |
| API | `app/api/` | `health`, `admin`, `payments`, `webhooks`, `telegram` |
| Providers | `app/providers/` | `llm/` (openai, stub) and `payments/` (stripe, yookassa, mock) behind interfaces |
| Prompts | `app/prompts/` | versioned persona prompt packs |
| Workers | `app/workers/` | `billing`, `maintenance`, `oracle_memory`, `telegram` |
| CLI | `app/cli/` | release, backfills, retention, verification, demos |

HTTP: `POST /telegram/webhook`, `POST /payments/webhooks/{provider}`, `POST /webhooks/stripe`,
`POST /webhooks/yookassa`, `GET /health/{live,ready}`, `GET /admin/metrics`,
`GET /admin/release-readiness`.

Telegram ingress is **at-least-once**: the API encrypts the update into
`telegram_update_inbox` keyed on `update_id`, commits, then returns `204`; workers claim rows
with `FOR UPDATE SKIP LOCKED` under a lease. Every business transition, payment operation and
ledger write must therefore be idempotent.

## Non-negotiable contracts

Each has a skill with the full detail; these are the one-line versions.

- **Safety** (`oracle-safety`) — classify input *before* it reaches a prompt; validate output
  *before* persistence; crisis stops the mystical flow entirely.
- **Money** (`billing-invariants`) — balance is derived from immutable `credit_transactions`;
  webhook is the source of truth; every grant, spend and refund is exactly once.
- **Privacy** (`privacy-encryption`) — sensitive content encrypted at rest, memory and birth
  data consent-gated, deletion purges content while immutable financial records survive.
- **Migrations** (`db-migrations`) — applied revisions are immutable; add new ones.
- **LLM** (`llm-contract`) — strict structured output, one controlled repair, versioned
  prompts, untrusted data never merged into instructions.
- **Engines** (`astrology-engine`) — deterministic and versioned; unknown birth time means no
  ascendant and no houses.

## Definition of done (`AGENTS.md`)

1. acceptance criteria pass; 2. `make check` green; 3. `make db-verify` when migrations
changed; 4. compose config and production image still build; 5. errors have safe user-facing
behavior; 6. docs reflect the decision; 7. `make gates` green — billing, privacy and release
invariants not weakened.

Report the actual command output. A gate is never made green by deleting a test node ID or
loosening an assertion; weakening an invariant needs an explicit architecture decision in the
PR description.

## Git / CI workflow

Branch from `main` → one ORA ticket or one narrow vertical slice per PR → green
`HeartSignal Baseline CI` → merge. Never combine code extraction, platform refactoring and
product behavior changes in one PR. Run `make check` locally before pushing. Commit and push
only when the user asks.

CI (`.github/workflows/heartsignal-ci.yml`) runs: format, lint, strict mypy, the Alembic
chain, the five protected gates, the full suite, compose validation, production image build.

## Automation (`.claude/`)

- **PreToolUse / Write** — blocks writing `.env*` secret files, and blocks editing an Alembic
  revision that is already committed (create a new one instead).
- **PreToolUse / Bash** — blocks dumping a real `.env`, live payment keys (`sk_live_…`) on a
  command line, `docker compose down -v`, `alembic downgrade base`, `alembic stamp head`,
  destructive SQL outside a test DB, and the billed `smoke_openai` CLI.
- **PostToolUse** — `ruff check --fix` + `ruff format` on edited Python (silent), then
  advisory `mypy` to stderr (never blocks). Expect edited files to come back reformatted.

A blocked call returns its reason — adjust, don't force it. If a guard is wrong, refine
`.claude/hooks/`, don't disable it.

## Skills (`.claude/skills/`) — auto-trigger by context

`ora-task` · `oracle-safety` · `billing-invariants` · `privacy-encryption` · `db-migrations` ·
`llm-contract` · `astrology-engine` · `ci-gates` · `release-ops` · `founder-cockpit`

## Agent routing

| Task | Agent | Model |
|---|---|---|
| Locate code / map a subsystem | `Explore` | haiku/sonnet |
| Plan a multi-step change | `Plan` | opus |
| Implement | `oh-my-claudecode:executor` | sonnet (opus if complex) |
| Debug / root-cause | `oh-my-claudecode:debugger` | opus |
| Review oracle output safety | `oracle-safety-reviewer` | opus |
| Audit a money path | `billing-auditor` | opus |
| Review a migration | `migration-reviewer` | sonnet |
| Product / prioritization / economics | `product-strategist` | opus |
| Generic diff review | `oh-my-claudecode:code-reviewer` | sonnet |
| Tests | `oh-my-claudecode:test-engineer` | sonnet |
| Verify done = done | `oh-my-claudecode:verifier` | sonnet |

Delegate multi-file changes, refactors, reviews and research; do trivial single-file edits
inline. Run independent tasks in parallel. Keep authoring and review in separate passes —
never self-approve in the same context.

## MCP servers (`.mcp.json`) — dev/local only, never point at production

- **`postgres-dev`** — read-only (`--access-mode=restricted`) on the local dev database.
  Needs `make db-up`.
- **`context7`** — current docs for aiogram / FastAPI / SQLAlchemy / Stripe.
- **`stripe`** — Stripe API tools, reads `${STRIPE_API_KEY}` from the environment.
  **`sk_test_…` only**; the key is never stored in the file. `export STRIPE_API_KEY=sk_test_…`
  before launching.

After editing `.mcp.json`, restart Claude Code and approve the project servers when prompted.

## Known gaps in the imported baseline

- `heartsignal/docs/deployment-render.md` references a repository-root `render.yaml` that was
  not carried over. Recreate it (or pick a different target platform) before a production
  deploy.
- Product naming is still `heartsignal` in the compose file, database name, image names and
  several docs, while `pyproject.toml` is already `bot-globa` — this is ORA-002.
- Following the README literally (`cp .env.example .env`) breaks host-side `pytest`:
  `.env.example` leaves several numeric variables empty, and pydantic-settings treats an
  empty value as a parse error where an absent one would fall back to its default. CI never
  hits this because it creates `.env` only after the test step. `make` works around it by
  stripping empty assignments when generating `.env`; the template itself is still worth
  fixing.
