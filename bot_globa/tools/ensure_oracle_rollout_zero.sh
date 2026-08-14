#!/usr/bin/env bash
# Ensure the non-secret Oracle launch guard is explicit without exposing .env.prod.
set -euo pipefail

ENV_FILE="${1:?usage: ensure_oracle_rollout_zero.sh <env-file>}"

test -f "${ENV_FILE}"

count="$(grep -c '^ORACLE_ROLLOUT_PERCENTAGE=' "${ENV_FILE}" || true)"
case "${count}" in
  0)
    # The application's default is safe, but make the launch posture explicit and auditable.
    printf '\nORACLE_ROLLOUT_PERCENTAGE=0\n' >> "${ENV_FILE}"
    ;;
  1)
    # Never rewrite an intentional non-zero value. A later limited-rollout change must be explicit.
    grep -Fxq 'ORACLE_ROLLOUT_PERCENTAGE=0' "${ENV_FILE}"
    ;;
  *)
    # Duplicate definitions are ambiguous; fail rather than guessing which dotenv parser wins.
    exit 1
    ;;
esac
