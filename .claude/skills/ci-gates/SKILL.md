---
name: ci-gates
description: Reproduce and debug this repo's CI locally — formatting, lint, strict mypy, the Alembic chain, the five protected regression gates, the full pytest suite, compose validation and the production image build. Use when CI is red, before pushing, or when the user asks "will this pass CI", "run the gates", "why did the pipeline fail".
---

# CI gates

Pipeline: `.github/workflows/heartsignal-ci.yml`, all steps run in `heartsignal/`.
Local equivalent, in CI order:

```bash
make fmt-check          # ruff format --check app tests migrations scripts
make lint               # ruff check  (E,F,I,UP,B,ASYNC,RUF)
make type               # mypy --strict app tests scripts
make db-verify          # alembic upgrade head -> downgrade -1 -> upgrade head
make db-reset-test
make gates              # the five protected gates, below
make test               # full pytest incl. postgres-marked tests
make compose-config
make docker-build
```

Everything at once: `make ci`. Everyday pre-push check: `make check`.

Postgres must be running for anything DB-backed: `make db-up`. Without `TEST_DATABASE_URL`
the `postgres`-marked tests silently **skip** — a green local run that skipped them proves
nothing. The Makefile always exports it and fails fast when the database is unreachable;
`make test-fast` is the explicit no-database run.

Dev and test databases are separate, as in CI: `heartsignal` for the app, `heartsignal_test`
for tests (`scripts/reset_test_database.py` refuses anything without a `_test` suffix).
`make db-verify` and `make db-reset-test` only touch the test one; `make db-reset-dev`
wipes the dev schema and requires `CONFIRM=yes`.

Two local traps worth knowing: gate scripts call bare `pytest`, so the venv must be first on
`PATH` (the Makefile handles it) — otherwise a global interpreter runs the suite and fails on
missing `astronomy`. And a verbatim `cp .env.example .env` breaks host-side pytest, because
empty numeric assignments are parse errors for pydantic-settings; `make` strips them when it
generates `.env`.

## The five protected gates

| Gate | Command | Protects |
|---|---|---|
| Platform invariants | `make gate-invariants` | credits ledger, exactly-once entitlement, refunds, deletion races, catalog snapshots |
| Oracle safety | `make gate-safety` | input classification, output validation, crisis handoff |
| Staging quality | `make gate-staging-quality` | structural/calculation/safety/style assertions on a fixed dataset |
| Release controls | `make gate-release-controls` | feature flags, rollout, kill switches, spend caps |
| Quality observability | `make gate-quality-observability` | LLM cost/latency, validation & repair telemetry |

A gate is an explicit list of pytest node IDs in `heartsignal/scripts/run_*.sh`. **Never make
a gate pass by deleting a node ID or loosening its assertion.** If the behavior genuinely
should change, that is an architecture decision written into the PR description, plus an
updated invariant doc.

## Debugging a red CI

1. Reproduce the exact failing step locally — do not guess from the log summary.
2. Test ordering matters here: CI resets the test DB between gates
   (`make db-reset-test`). A failure that only reproduces in the full suite is usually
   leftover state, not a flake.
3. Fix the cause. If a test is genuinely wrong, say so explicitly and show why.
4. Re-run the whole gate, not just the one node.

Artifacts: CI uploads `*-report.xml` per gate for 7 days —
`gh run view <id> --log` / `gh run download <id>`.

## Claiming done

Report actual command output. "Tests should pass" is not evidence; a pasted green
`make check` plus the relevant gate is.
