---
name: db-migrations
description: Alembic schema changes in this repo — creating a revision, verifying the chain, and the immutability rules around applied migrations and financial tables. Use when adding or changing a model in app/db/, when a migration test fails, or when the user says migration, alembic, schema, revision, upgrade or downgrade.
---

# Migrations

Chain lives in `heartsignal/migrations/versions/`, named `YYYYMMDD_NN_description.py`.
Config: `heartsignal/alembic.ini`, env: `heartsignal/migrations/env.py`.

## Immutable history

Applied revision IDs carry financial history and provider idempotency keys. **Never** edit
or renumber a committed revision — the `protect_secrets` PreToolUse hook blocks edits to
migration files that already exist in git. Always add a new revision instead.

## Workflow

```bash
make db-up                              # start postgres only
make db-upgrade                         # bring the local DB to head
# ...change models in app/db/...
make db-revision MSG="add reading symbols"
# review the generated file by hand — autogenerate misses server defaults,
# data backfills, enum changes, and index intent
make db-verify                          # upgrade -> downgrade -1 -> upgrade (what CI runs)
```

`make db-verify` is the gate. A revision without a working `downgrade` fails CI.

## Rules for a new revision

- Every `upgrade()` has a real `downgrade()`. If a downgrade is genuinely destructive, say so
  in the docstring and still make the chain reversible one step.
- Data migrations that touch user content must not decrypt it. Backfills over encrypted
  columns go through the application layer (see `app/cli/backfill_private_content.py`), not
  raw SQL.
- Do not drop or rename columns on financial tables (`credit_transactions`, orders,
  refunds, subscription periods). Add new ones; keep historical SKU codes readable.
- New tables holding user content need: encryption for sensitive fields, an owner FK, and a
  path in the account-deletion cascade. Add the deletion test in the same PR.
- Index intent belongs in the revision, not in a follow-up "perf" PR — concurrency tests
  depend on lock behavior.

## After a migration

```bash
make db-reset-test        # scripts/reset_test_database.py, same as CI
make test-postgres
make gate-invariants      # schema changes are the most common way to break an invariant
```

`tests/test_schema_health.py` and the `*_migration.py` tests assert chain and column shape —
read the failure before changing them.
