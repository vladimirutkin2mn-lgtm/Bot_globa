SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

# Use ./.venv when it exists, otherwise whatever is on PATH (activated venv, CI).
VENV ?= .venv
BIN := $(if $(wildcard $(VENV)/bin/python),$(VENV)/bin/,)

# The CI gate scripts call bare `pytest`, so the venv must also win on PATH —
# otherwise a global pytest runs the suite against the wrong environment.
export PATH := $(if $(BIN),$(abspath $(VENV)/bin):$(PATH),$(PATH))

PY      := $(BIN)python
PIP     := $(BIN)pip
RUFF    := $(BIN)ruff
MYPY    := $(BIN)mypy
PYTEST  := $(BIN)pytest
ALEMBIC := $(BIN)alembic

COMPOSE := docker compose
SRC     := app tests migrations scripts

# Host-side connections to the Dockerised postgres from docker-compose.yml.
# The dev database and the test database are separate, exactly like CI —
# scripts/reset_test_database.py refuses to touch anything without a `_test` suffix.
DB_USER      ?= bot_globa
DB_NAME      ?= bot_globa
TEST_DB_NAME ?= bot_globa_test

LOCAL_DB_URL      ?= postgresql+asyncpg://$(DB_USER):$(DB_USER)@localhost:5432/$(DB_NAME)
TEST_DATABASE_URL ?= postgresql+asyncpg://$(DB_USER):$(DB_USER)@localhost:5432/$(TEST_DB_NAME)
export TEST_DATABASE_URL

# Minimal env so alembic/CLI can boot on the host without a full .env.
BOOT_ENV := TELEGRAM_BOT_TOKEN=123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA \
	CONTENT_ENCRYPTION_KEY=local-only-key

DB_ENV      := DATABASE_URL=$(LOCAL_DB_URL) $(BOOT_ENV)
TEST_DB_ENV := DATABASE_URL=$(TEST_DATABASE_URL) $(BOOT_ENV)

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------- quality ---

.PHONY: check
check: fmt-check lint type test ## Full local gate — run before every push

.PHONY: fmt
fmt: ## Format sources (ruff format)
	$(RUFF) format $(SRC)

.PHONY: fmt-check
fmt-check: ## Check formatting the way CI does
	$(RUFF) format --check $(SRC)

.PHONY: lint
lint: ## Lint (ruff check)
	$(RUFF) check $(SRC)

.PHONY: lint-fix
lint-fix: ## Lint with autofix
	$(RUFF) check --fix $(SRC)

.PHONY: type
type: ## Strict type check (mypy)
	$(MYPY) app tests scripts

# ------------------------------------------------------------------ tests ---

# TEST_DATABASE_URL is exported above, so postgres-marked tests never silently skip.
# The flip side: they need a reachable database. require-db fails fast with a clear
# message instead of a wall of connection errors.
.PHONY: require-db
require-db:
	@$(PY) -c "import socket,sys; s=socket.socket(); s.settimeout(1); sys.exit(s.connect_ex(('localhost',5432)))" \
		|| { echo 'PostgreSQL is not reachable on localhost:5432. Run `make db-up` first (or `make test-fast` to skip DB tests).'; exit 1; }
	@$(MAKE) --no-print-directory db-create-test

# Running the full stack needs a .env (services declare env_file), bootstrapped from the
# template the same way CI does.
#
# Empty assignments are stripped: pydantic-settings also reads ./.env, and an empty value
# for a numeric variable is a parse error, whereas an absent one falls back to its default.
# A verbatim `cp .env.example .env` therefore breaks host-side pytest. Real secrets are
# still filled in by hand, never generated here.
.env:
	@grep -v -E '^[A-Za-z_][A-Za-z0-9_]*=[[:space:]]*$$' .env.example > .env
	@echo 'Created .env from .env.example (empty assignments stripped).'
	@echo 'Set TELEGRAM_BOT_TOKEN and CONTENT_ENCRYPTION_KEY by hand before running the stack.'

.PHONY: env
env: .env ## Create .env from .env.example when missing (compose only — see the warning)

# Created directly over the wire, deliberately not via `docker compose exec`, so the
# test path never requires a .env file.
.PHONY: db-create-test
db-create-test: ## Create the $(TEST_DB_NAME) database if it does not exist
	@DB_USER=$(DB_USER) TEST_DB_NAME=$(TEST_DB_NAME) $(PY) tools/create_test_db.py

.PHONY: test
test: require-db ## Full test suite (needs postgres — see test-fast)
	$(PYTEST)

.PHONY: test-fast
test-fast: ## Skip tests that need a real PostgreSQL (no database required)
	TEST_DATABASE_URL= $(PYTEST) -m "not postgres"

.PHONY: coverage
coverage: require-db ## Full suite with a branch-coverage report for app/
	$(PYTEST) --cov --cov-report=term-missing --cov-report=xml

.PHONY: test-postgres
test-postgres: require-db ## Only the PostgreSQL integration tests
	$(PYTEST) -m postgres

.PHONY: db-reset-test
db-reset-test: require-db ## Drop and recreate the test schema (same script CI uses)
	$(PY) scripts/reset_test_database.py

# ------------------------------------------------------------------ gates ---
# The protected regression gates CI runs before the full suite. Failing one of
# these means a production invariant changed — never "fix" it by editing the
# gate list without an explicit architecture decision.

.PHONY: gates
gates: require-db gate-invariants gate-safety gate-staging-quality gate-release-controls gate-quality-observability ## Run every protected CI gate

.PHONY: gate-invariants
gate-invariants: ## Billing / privacy / delivery characterization gate
	bash scripts/run_platform_invariants.sh

.PHONY: gate-safety
gate-safety: ## Oracle safety regression gate
	bash scripts/run_oracle_safety_gate.sh

.PHONY: gate-staging-quality
gate-staging-quality: ## Oracle staging quality gate
	ORACLE_STAGING_EXPECTED_LLM_PROVIDER=stub ORACLE_STAGING_EXPECTED_LLM_MODEL=stub \
		bash scripts/run_oracle_staging_quality_gate.sh

.PHONY: gate-release-controls
gate-release-controls: ## Limited-release controls gate
	bash scripts/run_oracle_release_controls_gate.sh

.PHONY: gate-quality-observability
gate-quality-observability: ## Cost & quality observability gate
	$(PY) scripts/reset_test_database.py
	bash scripts/run_oracle_quality_observability_gate.sh

.PHONY: gate-product-analytics
gate-product-analytics: ## Product event taxonomy gate
	bash scripts/run_oracle_product_analytics_gate.sh

.PHONY: ci
ci: fmt-check lint type db-verify db-reset-test gates test compose-config ## Reproduce the CI pipeline locally

# --------------------------------------------------------------- database ---

.PHONY: db-up
db-up: ## Start only PostgreSQL (for host-side dev / IDE / tests)
	$(COMPOSE) up -d postgres

.PHONY: db-upgrade
db-upgrade: require-db ## alembic upgrade head (host)
	$(DB_ENV) $(ALEMBIC) upgrade head

.PHONY: db-current
db-current: ## Show the currently applied revision
	$(DB_ENV) $(ALEMBIC) current

.PHONY: db-history
db-history: ## Show the migration chain
	$(DB_ENV) $(ALEMBIC) history

.PHONY: db-reset-dev
db-reset-dev: require-db ## DESTRUCTIVE: wipe the dev database schema. Needs CONFIRM=yes
	@test "$(CONFIRM)" = "yes" || { echo 'Refusing: this drops every table in "$(DB_NAME)". Re-run with CONFIRM=yes.'; exit 1; }
	@DB_USER=$(DB_USER) TEST_DB_NAME=$(DB_NAME) RESET=1 $(PY) tools/create_test_db.py

# Runs against the disposable test database, exactly like CI — never against the dev DB,
# which may hold data you care about.
.PHONY: db-verify
db-verify: require-db db-reset-test ## CI migration chain: upgrade -> downgrade -1 -> upgrade
	$(TEST_DB_ENV) $(ALEMBIC) upgrade head
	$(TEST_DB_ENV) $(ALEMBIC) downgrade -1
	$(TEST_DB_ENV) $(ALEMBIC) upgrade head
	@$(MAKE) --no-print-directory db-reset-test

.PHONY: db-revision
db-revision: ## New autogenerated revision: make db-revision MSG="describe change"
	@test -n "$(MSG)" || { echo 'MSG is required: make db-revision MSG="add reading table"'; exit 1; }
	$(DB_ENV) $(ALEMBIC) revision --autogenerate -m "$(MSG)"

# ------------------------------------------------------------------ stack ---

.PHONY: up
up: .env ## Build and start the whole dev stack
	$(COMPOSE) up --build -d

.PHONY: down
down: ## Stop the stack (keeps the postgres volume)
	$(COMPOSE) down

.PHONY: ps
ps: ## Show stack status
	$(COMPOSE) ps

.PHONY: logs
logs: ## Follow api logs (override: make logs S=bot)
	$(COMPOSE) logs -f --tail 100 $(or $(S),api)

.PHONY: sh
sh: ## Shell inside the api container
	$(COMPOSE) exec api bash

.PHONY: compose-config
compose-config: .env ## Validate the compose file the way CI does
	$(COMPOSE) config --quiet

.PHONY: docker-build
docker-build: ## Build the production image
	docker build --tag bot-globa:local .

.PHONY: health
health: ## Liveness + readiness probes
	curl --fail -s http://localhost:8000/health/live && echo
	curl --fail -s http://localhost:8000/health/ready && echo

# -------------------------------------------------------------------- dev ---

.PHONY: install
install: ## Create ./.venv from uv.lock (exact versions, same as CI)
	uv sync --frozen --extra dev

.PHONY: lock
lock: ## Re-resolve uv.lock after changing dependencies in pyproject.toml
	uv lock

.PHONY: deploy-prod-remote
deploy-prod-remote: ## Sync, build, migrate and smoke the shared-host production stack
	DEPLOY_HOST="$(DEPLOY_HOST)" DEPLOY_PATH="$(DEPLOY_PATH)" DEPLOY_SSH_OPTS='$(DEPLOY_SSH_OPTS)' \
	SKIP_SYNC="$(SKIP_SYNC)" SKIP_MIGRATIONS="$(SKIP_MIGRATIONS)" RUN_SMOKE="$(RUN_SMOKE)" \
	bash tools/deploy_prod_remote.sh

.PHONY: smoke-prod-remote
smoke-prod-remote: ## Verify an already deployed release
	DEPLOY_HOST="$(DEPLOY_HOST)" DEPLOY_PATH="$(DEPLOY_PATH)" DEPLOY_SSH_OPTS='$(DEPLOY_SSH_OPTS)' \
	bash tools/smoke_prod_remote.sh

.PHONY: api
api: ## Run the API on the host with reload
	$(BIN)uvicorn app.api.main:app --reload

.PHONY: bot
bot: ## Run the bot on the host (long polling when TELEGRAM_WEBHOOK_URL is empty)
	$(PY) -m app.bot.main

.PHONY: demo
demo: ## Safe fictional end-to-end analysis demo (stub LLM)
	$(PY) -m app.cli.demo_analysis

.PHONY: verify-deployment
verify-deployment: ## Release readiness / deployment verification CLI
	$(PY) -m app.cli.verify_deployment
