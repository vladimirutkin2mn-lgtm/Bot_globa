#!/usr/bin/env bash
# PostToolUse (Write|Edit|MultiEdit): advisory strict type check on the edited file.
# Prints errors to stderr for the agent to see. Never blocks (always exit 0):
# a single file in isolation can report false positives that `make type` does not.
set -uo pipefail

payload="$(cat)"
file_path="$(printf '%s' "$payload" | python3 -c 'import json,sys; print((json.load(sys.stdin).get("tool_input") or {}).get("file_path",""))' 2>/dev/null)"

[[ "$file_path" == *.py ]] || exit 0
[[ -f "$file_path" ]] || exit 0

root="${CLAUDE_PROJECT_DIR:-.}/heartsignal"
cd "$root" 2>/dev/null || exit 0

command -v mypy >/dev/null 2>&1 || exit 0

out="$(mypy --no-error-summary "$file_path" 2>&1)"
if [[ -n "$out" ]]; then
  echo "mypy (advisory, run 'make type' for the authoritative check):" >&2
  echo "$out" >&2
fi
exit 0
