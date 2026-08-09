---
description: Run the five protected CI gates and explain any failure
---

Ensure postgres is up (`make db-up`), then run `make gates` from the repository root.

For each failing gate:

1. Name the exact pytest node that failed and the invariant it protects
   (`heartsignal/docs/platform-invariants.md`, `.claude/skills/ci-gates/SKILL.md`).
2. Explain in one sentence what real-world behavior broke — a double charge, a leaked
   plaintext, an unsafe claim reaching the user — not just the assertion text.
3. Propose the fix in the product code. Never propose editing the gate list.

If everything is green, say so with the output and stop.
