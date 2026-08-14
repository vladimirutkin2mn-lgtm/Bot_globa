#!/usr/bin/env bash
# Verify the isolated staging release without exposing any configured secrets.
set -euo pipefail

DEPLOY_HOST="${DEPLOY_HOST:?Set DEPLOY_HOST for the staging host}"
DEPLOY_PATH="${DEPLOY_PATH:-/opt/bot_globa_staging}"
DEPLOY_SSH_OPTS="${DEPLOY_SSH_OPTS:-}"
PUBLIC_STAGING_URL="${PUBLIC_STAGING_URL:-}"
COMPOSE="docker compose -p bot_globa_staging -f docker-compose.staging.yml --env-file .env.staging --env-file .env.staging.release"

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

echo "==> Staging container health"
run_remote "cd ${DEPLOY_PATH} && test -f .env.staging && test -f .env.staging.release && ${COMPOSE} ps"

echo "==> Staging liveness and readiness inside the network"
run_remote "cd ${DEPLOY_PATH} && ${COMPOSE} exec -T api python -c \"
import urllib.request
for path in ('/health/live', '/health/ready'):
    with urllib.request.urlopen('http://127.0.0.1:8000' + path, timeout=5) as response:
        assert response.status == 200, (path, response.status)
        print(path, response.status)
\""

echo "==> Staging deployment verification"
run_remote "cd ${DEPLOY_PATH} && ${COMPOSE} exec -T api python -m app.cli.verify_deployment"

echo "==> Staging release identity and readiness endpoint"
run_remote "cd ${DEPLOY_PATH} && ${COMPOSE} exec -T api python -c \"
import json
import os
import urllib.request
request = urllib.request.Request(
    'http://127.0.0.1:8000/admin/release-readiness',
    headers={'X-Admin-Token': os.environ['ADMIN_API_TOKEN']},
)
with urllib.request.urlopen(request, timeout=5) as response:
    assert response.status == 200, response.status
    payload = json.load(response)
assert payload['app_env'] == 'staging', payload['app_env']
assert payload['code_sha'], 'missing code_sha'
assert payload['schema_revision'], 'missing schema_revision'
assert payload['checklist_version'], 'missing checklist_version'
print(
    'release-readiness',
    payload['app_env'],
    payload['code_sha'][:12],
    payload['schema_revision'],
    payload['checklist_version'],
    'blockers=' + str(len(payload['blockers'])),
)
\""

if [[ -n "${PUBLIC_STAGING_URL}" ]]; then
  PUBLIC_STAGING_URL="${PUBLIC_STAGING_URL%/}"
  if [[ "${PUBLIC_STAGING_URL}" != https://* ]]; then
    echo "Refusing public staging smoke: PUBLIC_STAGING_URL must use https://"
    exit 1
  fi
  if [[ "${PUBLIC_STAGING_URL}" == *\?* || "${PUBLIC_STAGING_URL}" == *\#* ]]; then
    echo "Refusing public staging smoke: URL must be a clean base URL without query or fragment"
    exit 1
  fi

  echo "==> Public staging HTTPS liveness and readiness"
  for path in /health/live /health/ready; do
    status="$(
      curl --silent --show-error --max-time 15 \
        --output /dev/null --write-out '%{http_code}' \
        "${PUBLIC_STAGING_URL}${path}"
    )"
    if [[ "${status}" != "200" ]]; then
      echo "Public staging smoke failed: ${PUBLIC_STAGING_URL}${path} returned HTTP ${status}; direct HTTP 200 required"
      exit 1
    fi
    echo "${PUBLIC_STAGING_URL}${path} 200"
  done
fi
