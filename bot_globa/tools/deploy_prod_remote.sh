#!/usr/bin/env bash
# Deploy this stack to the shared host: sync, build, migrate, smoke.
#
# The host already runs other products behind one Caddy instance. This stack publishes no
# port and joins Caddy's external `web` network, so it cannot collide with them. It never
# touches their compose project.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

DEPLOY_HOST="${DEPLOY_HOST:?Set DEPLOY_HOST, for example root@example.host}"
DEPLOY_PATH="${DEPLOY_PATH:-/opt/bot_globa}"
DEPLOY_SSH_OPTS="${DEPLOY_SSH_OPTS:-}"
SKIP_SYNC="${SKIP_SYNC:-0}"
SKIP_MIGRATIONS="${SKIP_MIGRATIONS:-0}"
RUN_SMOKE="${RUN_SMOKE:-1}"
REQUIRE_ORACLE_ROLLOUT_ZERO="${REQUIRE_ORACLE_ROLLOUT_ZERO:-0}"
COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env.prod"

SSH_ARGS=()
if [[ -n "${DEPLOY_SSH_OPTS}" ]]; then
  # shellcheck disable=SC2206
  SSH_ARGS=( ${DEPLOY_SSH_OPTS} )
fi

run_remote() {
  if [[ ${#SSH_ARGS[@]} -gt 0 ]]; then
    ssh "${SSH_ARGS[@]}" "${DEPLOY_HOST}" "$1"
  else
    ssh "${DEPLOY_HOST}" "$1"
  fi
}

if [[ "${SKIP_SYNC}" != "1" ]]; then
  echo "==> Syncing sources"
  rsync -az --delete \
    --exclude '.git/' --exclude '.venv/' --exclude '__pycache__/' \
    --exclude '.mypy_cache/' --exclude '.ruff_cache/' --exclude '.pytest_cache/' \
    --exclude '.env' --exclude '.env.prod' \
    ${DEPLOY_SSH_OPTS:+-e "ssh ${DEPLOY_SSH_OPTS}"} \
    "${SCRIPT_DIR}/../" "${DEPLOY_HOST}:${DEPLOY_PATH}/"
fi

echo "==> Refusing to continue without a production environment file"
run_remote "test -f ${DEPLOY_PATH}/.env.prod"

if [[ "${REQUIRE_ORACLE_ROLLOUT_ZERO}" == "1" ]]; then
  echo "==> Verifying first-deploy Oracle rollout is exactly zero"
  if ! run_remote "grep -Eq '^ORACLE_ROLLOUT_PERCENTAGE=0$' ${DEPLOY_PATH}/.env.prod"; then
    echo "Refusing first-deploy verification: set ORACLE_ROLLOUT_PERCENTAGE=0 in the server-side .env.prod"
    exit 1
  fi
fi

echo "==> Verifying the proxy-owned network already exists"
if ! run_remote "docker network inspect web >/dev/null 2>&1"; then
  echo "Refusing deployment: external Docker network 'web' is missing. Start/fix the proxy stack first."
  exit 1
fi

echo "==> Building release images"
run_remote "cd ${DEPLOY_PATH} && ${COMPOSE} build"

echo "==> Starting the database"
run_remote "cd ${DEPLOY_PATH} && ${COMPOSE} up -d --wait --wait-timeout 120 db"

if [[ "${SKIP_MIGRATIONS}" != "1" ]]; then
  echo "==> Applying migrations under an advisory lock"
  # -T and </dev/null because `compose run` claims a TTY and reads stdin: without both it
  # either refuses to start on a CI runner or silently swallows the rest of the script.
  run_remote "cd ${DEPLOY_PATH} && ${COMPOSE} run --rm -T --no-deps api python -m app.cli.release </dev/null"
fi

echo "==> Starting the application stack"
if ! run_remote "cd ${DEPLOY_PATH} && ${COMPOSE} up -d --no-build --wait --wait-timeout 180"; then
  echo "==> Stack failed to become healthy; collecting safe diagnostics"
  run_remote "cd ${DEPLOY_PATH} && ${COMPOSE} ps && ${COMPOSE} logs --tail=200 api"
  exit 1
fi

echo "==> Verifying the stable API alias on external network web"
if ! run_remote "cd ${DEPLOY_PATH} && api_container=\$(${COMPOSE} ps -q api) && test -n \"\$api_container\" && docker inspect \"\$api_container\" --format '{{json .NetworkSettings.Networks.web.Aliases}}' | grep -Fq '\"bot-globa-api\"'"; then
  echo "Refusing deployment verification: API container is missing alias 'bot-globa-api' on network 'web'."
  exit 1
fi

if [[ "${RUN_SMOKE}" != "1" ]]; then
  exit 0
fi

echo "==> Smoke checking the deployed release"
bash "${SCRIPT_DIR}/smoke_prod_remote.sh"
