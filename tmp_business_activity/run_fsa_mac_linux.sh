#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m pip install -r requirements_fsa.txt
python3 enrich_fsa_1000_selenium.py
echo
echo "Done. Results: output_fsa_1000/fsa_1000.csv"
