#!/usr/bin/env bash
# PostToolUse (Write|Edit|MultiEdit): autofix + format edited Python files.
# Silent on success; never blocks the agent.
set -uo pipefail

payload="$(cat)"
file_path="$(printf '%s' "$payload" | python3 -c 'import json,sys; print((json.load(sys.stdin).get("tool_input") or {}).get("file_path",""))' 2>/dev/null)"

[[ "$file_path" == *.py ]] || exit 0
[[ -f "$file_path" ]] || exit 0

cd "${CLAUDE_PROJECT_DIR:-.}/heartsignal" 2>/dev/null || exit 0

ruff check --fix --quiet "$file_path" >/dev/null 2>&1
ruff format --quiet "$file_path" >/dev/null 2>&1
exit 0
