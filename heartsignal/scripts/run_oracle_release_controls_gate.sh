#!/usr/bin/env bash
set -euo pipefail

pytest \
  tests/test_oracle_release_controls.py \
  tests/test_oracle_release_controls_postgres.py \
  "$@"
