#!/usr/bin/env python3
"""PreToolUse guard (Write|Edit|MultiEdit).

Two rules:

1. Secret env files (`.env`, `.env.prod`, ...) are never written by the agent.
   `*.example` templates stay editable.
2. Alembic revisions that are already committed are immutable — the migration
   chain and its revision IDs carry financial history (see AGENTS.md and
   `heartsignal/docs/platform-invariants.md`). A brand-new, uncommitted
   revision file is still editable.

Exit 2 cancels the tool call and feeds the reason back to the agent.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys


def block(reason: str) -> int:
    print(f"BLOCKED: {reason}", file=sys.stderr)
    return 2


def is_tracked(path: str) -> bool:
    """True when the file already exists in git HEAD (i.e. it is applied history)."""
    repo = os.path.dirname(path) or "."
    try:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", path],
            cwd=repo,
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0

    tool_input = data.get("tool_input") or {}
    file_path = tool_input.get("file_path") or ""
    if not file_path:
        return 0

    base = os.path.basename(file_path)

    # 1) Secret env files.
    if not base.endswith(".example") and (base == ".env" or base.startswith(".env.")):
        return block(
            f"'{file_path}' is a secret env file. Edit it by hand; "
            "never write secrets through the agent or into model context."
        )

    # 2) Committed Alembic revisions are immutable.
    norm = file_path.replace(os.sep, "/")
    if "/migrations/versions/" in norm and base.endswith(".py") and is_tracked(file_path):
        return block(
            f"'{base}' is an already-committed Alembic revision. Revision IDs and applied "
            "migrations are immutable (AGENTS.md, docs/platform-invariants.md). "
            'Create a NEW revision instead: `make db-revision MSG="..."`.'
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
