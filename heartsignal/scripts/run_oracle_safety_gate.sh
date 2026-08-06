#!/usr/bin/env bash
set -euo pipefail

pytest \
  tests/test_oracle_safety_regression_gate.py \
  tests/test_oracle_input_safety.py \
  tests/test_reading_output_safety.py \
  tests/test_reading_generation_output_safety.py \
  tests/test_oracle_crisis_handoff.py \
  tests/test_tarot_input_safety_gate.py \
  tests/test_tarot_safety_middleware.py \
  "$@"
