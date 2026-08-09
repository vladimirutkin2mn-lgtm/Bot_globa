#!/usr/bin/env bash
# Prove a deployed release is actually serving before anyone is pointed at it.
set -euo pipefail

DEPLOY_HOST="${DEPLOY_HOST:?Set DEPLOY_HOST, for example root@example.host}"
DEPLOY_PATH="${DEPLOY_PATH:-/opt/bot_globa}"
DEPLOY_SSH_OPTS="${DEPLOY_SSH_OPTS:-}"
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

echo "==> Container health"
run_remote "cd ${DEPLOY_PATH} && ${COMPOSE} ps"

echo "==> Liveness and readiness inside the network"
run_remote "cd ${DEPLOY_PATH} && ${COMPOSE} exec -T api python -c \"
import urllib.request
for path in ('/health/live', '/health/ready'):
    with urllib.request.urlopen('http://127.0.0.1:8000' + path, timeout=5) as response:
        assert response.status == 200, (path, response.status)
        print(path, response.status)
\""

echo "==> Deployment verification (webhook configuration, delivery, backlog)"
run_remote "cd ${DEPLOY_PATH} && ${COMPOSE} exec -T api python -m app.cli.verify_deployment"
