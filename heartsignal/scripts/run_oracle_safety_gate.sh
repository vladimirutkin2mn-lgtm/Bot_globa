#!/usr/bin/env bash
set -euo pipefail

pytest \
  tests/test_oracle_safety_regression_gate.py \
  tests/test_oracle_input_safety.py \
  tests/test_reading_output_safety.py \
  tests/test_reading_generation_output_safety.py \
  tests/test_oracle_crisis_handoff.py \
  tests/test_persona_input_safety_gate.py \
  tests/test_reading_safety_middleware.py \
  tests/test_horoscope_result_validator.py \
  tests/test_horoscope_reading.py \
  "$@"
