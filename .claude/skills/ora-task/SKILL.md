---
name: ora-task
description: Execute one ORA backlog task (ORA-xxx) end to end in this repo — read the right sources of truth, scope a single vertical slice, implement, and prove definition-of-done. Use when the user names an ORA ticket, says "next task", "continue the backlog", "implement the tarot/love/psychologist/horoscope slice", or asks what to work on next.
---

# ORA task workflow

The backlog is `docs/MVP_BACKLOG.md`. Every unit of work is one ORA ticket or one narrow
vertical slice — never a bundle of extraction + refactor + behavior change.

## 1. Read before touching code

In this order (from `AGENTS.md`):

1. `docs/FABRIC_BOT_ADAPTATION_PLAN.md` — migration strategy
2. `docs/MVP_BACKLOG.md` — the ticket and its acceptance criteria
3. `heartsignal/docs/platform-core-boundaries.md` — what may depend on what
4. `heartsignal/docs/platform-invariants.md` — protected production behavior
5. existing code + tests
6. `heartsignal/PRODUCT_SPEC.md` / `TASKS.md` — **legacy only**, historical HeartSignal behavior

When docs conflict, the repository-level oracle plan wins over the legacy HeartSignal docs.

## 2. Scope the slice

Pick the smallest change that satisfies the ticket's acceptance criteria. Do not:

- combine code extraction, platform refactoring and product behavior in one PR;
- rewrite ledger / payment / privacy / delivery services inside a `Reading` service —
  wrap them with adapters instead;
- make a platform module (`app/platform/`, `app/providers/`, billing, privacy) depend on
  persona-specific code. Dependency flows domain → platform, never back.

Runtime identity lives in `app.platform.identity` — do not re-derive it locally.

## 3. Where code goes

| Concern | Location |
|---|---|
| Pure domain rules, value objects, validators | `heartsignal/app/domain/` |
| Orchestration / use cases | `heartsignal/app/services/` |
| DB models & tables | `heartsignal/app/db/` |
| Data access | `heartsignal/app/repositories/` |
| Telegram handlers, keyboards, FSM, renderers | `heartsignal/app/bot/` |
| HTTP endpoints | `heartsignal/app/api/` |
| External systems behind interfaces | `heartsignal/app/providers/` |
| Persona prompts / prompt packs | `heartsignal/app/prompts/` |
| Background loops | `heartsignal/app/workers/` |
| One-off / operational commands | `heartsignal/app/cli/` |

Persona additions are versioned (`tarot_reader_v1`, …) and registered through
`app/services/persona_registry.py`; global policy, persona style and runtime request stay
separate, and prompt/schema versions are persisted with each result.

## 4. Definition of done (AGENTS.md, non-negotiable)

A task is complete only when **all** hold:

1. the ticket's acceptance criteria pass;
2. `make check` is green (format, lint, `mypy --strict`, tests);
3. when migrations changed: `make db-verify` (upgrade → downgrade -1 → upgrade) passes;
4. `make compose-config` and `make docker-build` still succeed;
5. errors have safe user-facing behavior (no internal codes, no private content);
6. docs reflect the architectural decision;
7. billing, privacy and release invariants are not weakened — `make gates` is green.

State the evidence (actual command output) before claiming completion. See `ci-gates`.

## 5. Related skills

`oracle-safety` (every generated result), `billing-invariants` (anything touching money),
`privacy-encryption` (any user content), `db-migrations` (schema), `ci-gates` (proving done).
