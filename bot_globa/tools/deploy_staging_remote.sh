#!/usr/bin/env bash
# Deploy an isolated staging release used only for the five live release gates.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

DEPLOY_HOST="${DEPLOY_HOST:?Set DEPLOY_HOST for the staging host}"
DEPLOY_PATH="${DEPLOY_PATH:-/opt/bot_globa_staging}"
DEPLOY_SSH_OPTS="${DEPLOY_SSH_OPTS:-}"
SKIP_SYNC="${SKIP_SYNC:-0}"
SKIP_MIGRATIONS="${SKIP_MIGRATIONS:-0}"
RUN_SMOKE="${RUN_SMOKE:-1}"
PUBLIC_STAGING_URL="${PUBLIC_STAGING_URL:-}"
RELEASE_CODE_SHA="${RELEASE_CODE_SHA:?Set RELEASE_CODE_SHA to the exact deployed 40-char commit}"
RELEASE_CHECKLIST_VERSION="${RELEASE_CHECKLIST_VERSION:-m5-live-v1}"
COMPOSE="docker compose -p bot_globa_staging -f docker-compose.staging.yml --env-file .env.staging --env-file .env.staging.release"

if [[ ! "${RELEASE_CODE_SHA}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Refusing staging deploy: RELEASE_CODE_SHA must be an exact 40-character lowercase git SHA."
  exit 1
fi
if [[ ! "${RELEASE_CHECKLIST_VERSION}" =~ ^[a-z0-9][a-z0-9._-]{0,63}$ ]]; then
  echo "Refusing staging deploy: RELEASE_CHECKLIST_VERSION has an invalid format."
  exit 1
fi

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
  echo "==> Syncing staging sources"
  rsync -az --delete \
    --exclude '.git/' --exclude '.venv/' --exclude '__pycache__/' \
    --exclude '.mypy_cache/' --exclude '.ruff_cache/' --exclude '.pytest_cache/' \
    --exclude '.env' --exclude '.env.prod' --exclude '.env.staging' \
    --exclude '.env.staging.release' \
    ${DEPLOY_SSH_OPTS:+-e "ssh ${DEPLOY_SSH_OPTS}"} \
    "${SCRIPT_DIR}/../" "${DEPLOY_HOST}:${DEPLOY_PATH}/"
fi

echo "==> Refusing to continue without a staging environment file"
run_remote "test -f ${DEPLOY_PATH}/.env.staging"

echo "==> Recording exact staging release identity"
run_remote "cd ${DEPLOY_PATH} && umask 077 && printf '%s\n' 'RELEASE_CODE_SHA=${RELEASE_CODE_SHA}' 'RELEASE_CHECKLIST_VERSION=${RELEASE_CHECKLIST_VERSION}' > .env.staging.release.tmp && mv .env.staging.release.tmp .env.staging.release"

echo "==> Verifying the proxy-owned network already exists"
if ! run_remote "docker network inspect web >/dev/null 2>&1"; then
  echo "Refusing staging deployment: external Docker network 'web' is missing."
  exit 1
fi

echo "==> Building staging release images"
run_remote "cd ${DEPLOY_PATH} && ${COMPOSE} build"

echo "==> Starting the isolated staging database"
run_remote "cd ${DEPLOY_PATH} && ${COMPOSE} up -d --wait --wait-timeout 120 db"

if [[ "${SKIP_MIGRATIONS}" != "1" ]]; then
  echo "==> Applying staging migrations under an advisory lock"
  run_remote "cd ${DEPLOY_PATH} && ${COMPOSE} run --rm -T --no-deps api python -m app.cli.release </dev/null"
fi

echo "==> Starting the isolated staging application stack"
if ! run_remote "cd ${DEPLOY_PATH} && ${COMPOSE} up -d --no-build --wait --wait-timeout 180"; then
  echo "==> Staging stack failed to become healthy; collecting safe diagnostics"
  run_remote "cd ${DEPLOY_PATH} && ${COMPOSE} ps && ${COMPOSE} logs --tail=200 api"
  exit 1
fi

echo "==> Verifying the stable staging API alias on external network web"
if ! run_remote "cd ${DEPLOY_PATH} && api_container=\$(${COMPOSE} ps -q api) && test -n \"\$api_container\" && docker inspect \"\$api_container\" --format '{{json .NetworkSettings.Networks.web.Aliases}}' | grep -Fq '\"bot-globa-staging-api\"'"; then
  echo "Refusing staging verification: API container is missing alias 'bot-globa-staging-api' on network 'web'."
  exit 1
fi

if [[ "${RUN_SMOKE}" != "1" ]]; then
  exit 0
fi

echo "==> Smoke checking the staging release"
PUBLIC_STAGING_URL="${PUBLIC_STAGING_URL}" bash "${SCRIPT_DIR}/smoke_staging_remote.sh"
