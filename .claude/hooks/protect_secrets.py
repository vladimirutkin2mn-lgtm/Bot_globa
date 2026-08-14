#!/usr/bin/env python3
"""PreToolUse guard (Write|Edit|MultiEdit).

Two rules:

1. Secret env files (`.env`, `.env.prod`, ...) are never written by the agent.
   `*.example` templates stay editable.
2. Alembic revisions that have reached the default branch are immutable — the
   migration chain and its revision IDs carry financial history (see AGENTS.md
   and `heartsignal/docs/platform-invariants.md`). A revision is editable while
   it exists only on a feature branch, because nothing has applied it yet:
   AGENTS.md forbids rewriting *applied* migrations, and CI runs every branch
   revision against a throwaway schema. Once it lands on `main` the deploy job
   may have applied it to production, and from then on the only correct change
   is a new revision.

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


def _git(args: list[str], cwd: str) -> subprocess.CompletedProcess[bytes] | None:
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None


def is_on_default_branch(path: str) -> bool:
    """True when the revision exists on the default branch, i.e. a deploy may have run it.

    Falls back to "assume it is protected" whenever the default branch cannot be resolved,
    so a detached checkout or a missing remote never turns the guard off silently.
    """

    repo = os.path.dirname(path) or "."
    tracked = _git(["ls-files", "--error-unmatch", "--", path], repo)
    if tracked is None or tracked.returncode != 0:
        return False

    top = _git(["rev-parse", "--show-toplevel"], repo)
    if top is None or top.returncode != 0:
        return True
    relative = os.path.relpath(os.path.abspath(path), top.stdout.decode().strip())
    for ref in ("origin/main", "main", "origin/master", "master"):
        exists = _git(["cat-file", "-e", f"{ref}:{relative}"], repo)
        if exists is None:
            return True
        if exists.returncode == 0:
            return True
        resolved = _git(["rev-parse", "--verify", "--quiet", ref], repo)
        if resolved is not None and resolved.returncode == 0:
            # The branch exists and does not carry this file: it is feature-branch only.
            return False
    return True


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

    # 2) Alembic revisions that reached the default branch are immutable.
    norm = file_path.replace(os.sep, "/")
    if "/migrations/versions/" in norm and base.endswith(".py") and is_on_default_branch(file_path):
        return block(
            f"'{base}' is an Alembic revision that already exists on the default branch, so "
            "a deploy may have applied it. Revision IDs and applied migrations are immutable "
            "(AGENTS.md, docs/platform-invariants.md). "
            'Create a NEW revision instead: `make db-revision MSG="..."`.'
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
