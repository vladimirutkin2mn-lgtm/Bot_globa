---
description: Full pre-merge verification — local CI plus the specialist reviewers the diff needs
---

Verify the current branch is safe to merge.

1. Show the diff scope: `git diff main...HEAD --stat`.
2. Run the local pipeline from `heartsignal/` and report **actual output**:
   `make check`, then `make gates`, plus `make db-verify` if
   `heartsignal/migrations/versions/` changed.
3. Dispatch the reviewers the diff actually needs, in parallel:
   - `oracle-safety-reviewer` — if prompts, personas, readings, validators or memory changed
   - `billing-auditor` — if anything under payments, credits, checkout, subscriptions or refunds changed
   - `migration-reviewer` — if migrations or `app/db/` changed
   - `oh-my-claudecode:code-reviewer` — otherwise
4. Report findings most-severe-first, then a single verdict line: ready to merge, or blocked
   with the specific blockers.

Never make a gate pass by removing a test node ID or loosening an assertion. If a gate is
genuinely wrong, say so and explain why — that is an architecture decision, not a fix.
