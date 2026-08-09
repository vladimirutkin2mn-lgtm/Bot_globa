#!/usr/bin/env python3
"""PreToolUse guard (Bash): block secret leaks and irreversible/destructive commands.

Precise by design — only clearly dangerous patterns are blocked, so normal work
is never interrupted. Exit 2 cancels the call; the reason is fed back to the agent.
"""

from __future__ import annotations

import json
import re
import sys


def block(reason: str) -> int:
    print(f"BLOCKED: {reason}", file=sys.stderr)
    return 2


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0

    cmd = (data.get("tool_input") or {}).get("command") or ""
    if not cmd:
        return 0
    low = cmd.lower()

    # `git commit -m "..."` is data, not execution — never block on message text.
    if re.search(r"\bgit\s+commit\b", low):
        return 0

    mentions_env = bool(re.search(r"\.env(\.[a-z0-9_]+)?\b", low))
    mentions_example = ".env.example" in low

    # 1) Secret leak: dumping a real .env into model context.
    if mentions_env and not mentions_example:
        if re.search(r"\b(cat|less|more|head|tail|strings|xxd|od|nl|bat|grep|rg)\b", low):
            return block(
                "this reads a secret .env file. Open it manually — keep secrets out of "
                "model context. `.env.example` is the safe reference for variable names."
            )
        if re.search(r"echo\b[^|]*\$\{?[a-z_]*(token|secret|api_key|password|encryption_key)", low):
            return block("this echoes a secret value.")

    # 2) Live payment credentials must never appear in a command line.
    if re.search(r"\b(sk_live_|rk_live_|pk_live_)", cmd):
        return block(
            "a live payment provider key is present in this command. Use test keys "
            "(sk_test_...) and keep live secrets in the deployment environment only."
        )

    # 3) Destroying the local database volume (loses migration state and dev data).
    if re.search(r"docker\s+compose\b.*\bdown\b", low) and re.search(
        r"(^|\s)(-v|--volumes)\b", low
    ):
        return block(
            "`docker compose down -v` deletes the postgres volume. Use `make down` "
            "(keeps data) — or say explicitly that the volume should be wiped."
        )

    # 4) Alembic destructive paths.
    if re.search(r"\balembic\b.*\bdowngrade\s+base\b", low):
        return block(
            "`alembic downgrade base` drops the whole schema including financial ledger "
            "tables. Verify migrations with the CI chain instead: `make db-verify` "
            "(upgrade → downgrade -1 → upgrade)."
        )
    if re.search(r"\balembic\b.*\bstamp\b", low) and "head" in low:
        return block(
            "`alembic stamp head` marks migrations applied without running them and can "
            "silently desync the schema. Run `alembic upgrade head` instead."
        )

    # 5) Dropping / truncating real tables outside a test database.
    if re.search(r"\b(drop\s+(table|schema|database)|truncate\s+table)\b", low) and not re.search(
        r"test|_test\b|reset_test_database", low
    ):
        return block(
            "destructive SQL against a non-test database. Use "
            "`python scripts/reset_test_database.py` for test resets."
        )

    # 6) Real OpenAI spend from an automated run.
    if "smoke_openai" in low and "llm_provider=stub" not in low:
        return block(
            "app.cli.smoke_openai issues a real, billed OpenAI call and is manual-only "
            "(never in CI). Run it by hand when you intend to pay for it."
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
