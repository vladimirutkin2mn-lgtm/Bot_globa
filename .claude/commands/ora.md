---
description: Start work on an ORA backlog ticket (or pick the next one on the critical path)
argument-hint: "[ORA-xxx | next]"
---

Work on: **$ARGUMENTS** (if empty or `next`, pick the next unchecked P0 ticket on the
critical path in `docs/MVP_BACKLOG.md`).

Follow the `ora-task` skill. Concretely:

1. Read the ticket and its acceptance criteria in `docs/MVP_BACKLOG.md`, plus
   `heartsignal/AGENTS.md` and any invariant doc the ticket touches.
2. Check `git log --oneline` for what already shipped, so you don't redo it.
3. State the slice you will implement and what you are explicitly leaving out. Stop and
   confirm if the ticket is larger than one vertical slice.
4. Implement in `heartsignal/`, one concern at a time.
5. Prove definition of done with real output: `make check`, plus `make db-verify` if
   migrations changed, plus the gates the change touches.
6. Summarize: what changed, which acceptance criteria are now met, what is still open.

Do not commit or push unless asked.
