#!/usr/bin/env bash
set -euo pipefail

pytest \
  tests/test_oracle_product_analytics.py \
  tests/test_oracle_event_taxonomy_postgres.py \
  tests/test_oracle_service_analytics_postgres.py \
  tests/test_reading_generation_product_analytics.py \
  "$@"
