#!/usr/bin/env bash
# Prove a deployed release is actually serving before anyone is pointed at it.
set -euo pipefail

DEPLOY_HOST="${DEPLOY_HOST:?Set DEPLOY_HOST, for example root@example.host}"
DEPLOY_PATH="${DEPLOY_PATH:-/opt/bot_globa}"
DEPLOY_SSH_OPTS="${DEPLOY_SSH_OPTS:-}"
PUBLIC_ORACLE_URL="${PUBLIC_ORACLE_URL:-}"
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

echo "==> Billing worker is running"
run_remote "cd ${DEPLOY_PATH} && billing_container=\$(${COMPOSE} ps -q billing-worker) && test -n \"\$billing_container\" && docker inspect \"\$billing_container\" --format '{{.State.Running}} {{.State.Restarting}}' | grep -Fxq 'true false'"

echo "==> Billing worker heartbeat is fresh"
run_remote "cd ${DEPLOY_PATH} && for attempt in \$(seq 1 15); do if ${COMPOSE} exec -T billing-worker python -c \"from pathlib import Path; import time; p=Path('/app/.numa-billing-worker-heartbeat'); age=time.time()-p.stat().st_mtime if p.exists() else 999.0; print(f'billing-worker heartbeat age={age:.1f}s'); raise SystemExit(0 if 0 <= age <= 45 else 1)\"; then exit 0; fi; sleep 2; done; echo 'billing-worker heartbeat missing or stale' >&2; exit 1"

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

if [[ -n "${PUBLIC_ORACLE_URL}" ]]; then
  PUBLIC_ORACLE_URL="${PUBLIC_ORACLE_URL%/}"
  if [[ "${PUBLIC_ORACLE_URL}" != https://* ]]; then
    echo "Refusing public smoke: PUBLIC_ORACLE_URL must use https://"
    exit 1
  fi
  if [[ "${PUBLIC_ORACLE_URL}" == *\?* || "${PUBLIC_ORACLE_URL}" == *\#* ]]; then
    echo "Refusing public smoke: PUBLIC_ORACLE_URL must be a clean base URL without query or fragment"
    exit 1
  fi

  echo "==> Public HTTPS liveness and readiness"
  for path in /health/live /health/ready; do
    status="$(
      curl --silent --show-error --max-time 15 \
        --output /dev/null --write-out '%{http_code}' \
        "${PUBLIC_ORACLE_URL}${path}"
    )"
    if [[ "${status}" != "200" ]]; then
      echo "Public smoke failed: ${PUBLIC_ORACLE_URL}${path} returned HTTP ${status}; direct HTTP 200 required"
      exit 1
    fi
    echo "${PUBLIC_ORACLE_URL}${path} 200"
  done
fi
