#!/usr/bin/env bash
# Validate the host-side staging configuration before any build, migration or service start.
set -euo pipefail

ENV_FILE="${STAGING_ENV_FILE:-.env.staging}"
PUBLIC_ENV_FILE="${STAGING_PUBLIC_ENV_FILE:-staging.public.env}"

fail() {
  echo "Staging preflight failed: $1" >&2
  exit 1
}

read_value() {
  local file="$1"
  local key="$2"
  local value

  value="$(awk -v key="${key}" '
    index($0, key "=") == 1 {
      value = substr($0, length(key) + 2)
      found = 1
    }
    END {
      if (found) {
        printf "%s", value
      }
    }
  ' "${file}")"
  value="${value%$'\r'}"

  if [[ ${#value} -ge 2 ]]; then
    if [[ "${value:0:1}" == '"' && "${value: -1}" == '"' ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "${value:0:1}" == "'" && "${value: -1}" == "'" ]]; then
      value="${value:1:${#value}-2}"
    fi
  fi

  printf '%s' "${value}"
}

is_placeholder() {
  local value="${1,,}"
  [[ -z "${value}" \
    || "${value}" == *"change_me"* \
    || "${value}" == *"change-me"* \
    || "${value}" == *"changeme"* \
    || "${value}" == *"example.invalid"* ]]
}

require_value() {
  local key="$1"
  local value
  value="$(read_value "${ENV_FILE}" "${key}")"
  if is_placeholder "${value}"; then
    fail "${key} is missing or still uses a placeholder"
  fi
}

require_public_flag() {
  local key="$1"
  local expected="$2"
  local value
  value="$(read_value "${PUBLIC_ENV_FILE}" "${key}")"
  if [[ "${value}" != "${expected}" ]]; then
    fail "${key} must be ${expected} in ${PUBLIC_ENV_FILE}"
  fi
}

[[ -f "${ENV_FILE}" ]] || fail "${ENV_FILE} does not exist"
[[ -r "${ENV_FILE}" ]] || fail "${ENV_FILE} is not readable"
[[ -f "${PUBLIC_ENV_FILE}" ]] || fail "${PUBLIC_ENV_FILE} does not exist"
[[ -r "${PUBLIC_ENV_FILE}" ]] || fail "${PUBLIC_ENV_FILE} is not readable"

app_env="$(read_value "${ENV_FILE}" APP_ENV)"
[[ "${app_env}" == "staging" ]] || fail "APP_ENV must be staging"

postgres_db="$(read_value "${ENV_FILE}" POSTGRES_DB)"
[[ "${postgres_db}" == "bot_globa_staging" ]] || fail "POSTGRES_DB must be bot_globa_staging"

database_url="$(read_value "${ENV_FILE}" DATABASE_URL)"
if is_placeholder "${database_url}" || [[ "${database_url}" != *"/bot_globa_staging"* ]]; then
  fail "DATABASE_URL must point to the isolated bot_globa_staging database"
fi

for key in \
  POSTGRES_PASSWORD \
  TELEGRAM_BOT_TOKEN \
  TELEGRAM_WEBHOOK_SECRET \
  CONTENT_ENCRYPTION_KEY \
  OPENAI_API_KEY \
  LLM_MODEL \
  PAYMENT_WEBHOOK_SECRET \
  YOOKASSA_SHOP_ID \
  YOOKASSA_SECRET_KEY \
  STRIPE_SECRET_KEY \
  STRIPE_WEBHOOK_SECRET \
  ADMIN_API_TOKEN; do
  require_value "${key}"
done

llm_provider="$(read_value "${ENV_FILE}" LLM_PROVIDER)"
[[ "${llm_provider}" == "openai" ]] || fail "LLM_PROVIDER must be openai for live staging gates"

telegram_webhook_url="$(read_value "${ENV_FILE}" TELEGRAM_WEBHOOK_URL)"
if is_placeholder "${telegram_webhook_url}" || [[ "${telegram_webhook_url}" != https://* ]]; then
  fail "TELEGRAM_WEBHOOK_URL must be a non-placeholder HTTPS URL"
fi

payment_public_base_url="$(read_value "${ENV_FILE}" PAYMENT_PUBLIC_BASE_URL)"
if is_placeholder "${payment_public_base_url}" || [[ "${payment_public_base_url}" != https://* ]]; then
  fail "PAYMENT_PUBLIC_BASE_URL must be a non-placeholder HTTPS URL"
fi

payment_provider="$(read_value "${ENV_FILE}" PAYMENT_PROVIDER)"
if [[ -z "${payment_provider}" || "${payment_provider}" == "mock" ]]; then
  fail "PAYMENT_PROVIDER must select a real sandbox provider"
fi

stripe_key="$(read_value "${ENV_FILE}" STRIPE_SECRET_KEY)"
if [[ "${stripe_key}" != sk_test_* && "${stripe_key}" != rk_test_* ]]; then
  fail "STRIPE_SECRET_KEY must be a Stripe test/restricted-test credential"
fi

require_public_flag BILLING_ENABLED true
require_public_flag STRIPE_ENABLED true
require_public_flag YOOKASSA_ENABLED true
require_public_flag SUBSCRIPTIONS_ENABLED true
require_public_flag REFUNDS_ENABLED true
require_public_flag ORACLE_ENABLED true

# Keep output intentionally free of values: this script may run inside GitHub Actions logs.
echo "Staging preflight passed: environment, isolation, HTTPS and sandbox credential shape are valid."
