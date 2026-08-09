#!/usr/bin/env bash
set -euo pipefail

pytest \
  tests/test_oracle_staging_quality_gate.py \
  tests/test_oracle_safety_regression_gate.py \
  tests/test_natal_chart.py \
  tests/test_horoscope_facts.py \
  tests/test_horoscope_result_validator.py \
  "$@"
