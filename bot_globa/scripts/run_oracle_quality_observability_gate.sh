#!/usr/bin/env bash
set -euo pipefail

pytest \
  tests/test_oracle_quality_observer.py \
  tests/test_oracle_quality_admin_postgres.py \
  tests/test_observability_settings.py \
  "$@"
