# Code style

The linters own formatting, import order, naming and security rules — run `make check`
and believe it. This document only covers the decisions a tool cannot make for you.

## Where code lives

Dependencies flow one way: `bot`/`api` → `services` → `repositories`/`db` → `domain`.
A module never imports from a layer above it.

| Layer | Path | Holds | Never holds |
|---|---|---|---|
| Domain | `app/domain/` | pure rules, value objects, validators | I/O, SQLAlchemy, aiogram, user-facing copy |
| Services | `app/services/` | use cases, orchestration, transactions | rendering, keyboards, Telegram types |
| Repositories | `app/repositories/` | data access, encrypted content | business rules |
| DB | `app/db/` | SQLAlchemy models, FSM, inbox tables | queries owned by a repository |
| Bot | `app/bot/` | aiogram routers, keyboards, renderers, copy | business rules, SQL |
| API | `app/api/` | FastAPI routers, composition root | business rules |
| Providers | `app/providers/` | LLM and payment adapters behind interfaces | domain knowledge |

Rendering is presentation: a renderer belongs in `app/bot/`, never in `app/services/`.

Platform modules (`app/platform/`, `app/providers/`, billing, privacy) must not import
persona-specific code. Runtime identity comes from `app.platform.identity`.

## Naming

| Thing | Rule | Example |
|---|---|---|
| Module | noun describing the subject, no `_service` suffix | `persona_reading.py` |
| Use case | `<Subject>UseCase` — one user-visible action | `PersonaReadingUseCase` |
| Service | `<Subject>Service` — a long-lived collaborator | `ReadingHistoryService` |
| Repository | `SqlAlchemy<Subject>Store` / `...Repository` | `SqlAlchemyReadingGenerationStore` |
| Interface | `Protocol`, named for the role, not the implementation | `SymbolDrawer` |
| Exception | ends in `Error` | `UnsupportedPersonaTopicError` |
| Enum | `StrEnum` with lowercase snake_case values | `ReadingGenerationStatus.ALREADY_PROCESSING` |
| Result object | frozen dataclass named `<Verb><Subject>Result`/`Outcome` | `PersonaPreviewOutcome` |

`_service` in a module name is legacy: new modules are named after the subject.

## Types and data

- Value objects and results: `@dataclass(frozen=True, slots=True)`, validated in
  `__post_init__`.
- Boundaries between layers: `typing.Protocol`, not ABCs and not concrete classes.
- Collections that cross a boundary are `tuple`, not `list`.
- `mypy --strict` passes with no `# type: ignore`. If you need one, the design is wrong.

## Suppressions

Every lint suppression lives in `pyproject.toml` with a comment explaining why. Inline
`# noqa` is allowed only when the reason is specific to that one line, and it must carry
the rule code and a reason:

```python
timeout: int = 30,  # noqa: ASYNC109 -- aiogram session contract
```

File-level `# ruff: noqa` headers are not used.

## User-facing copy

All Russian copy lives in the transport layer: `app/bot/texts.py` for shared strings and
`app/bot/persona_flows.py` for per-persona copy. A domain or service module that contains
a Russian sentence is a layering bug.

Telegram callback data is capped at 64 bytes and a reading UUID already costs 36, so
callback namespaces are short (`tarot`, `love`, `psy`) even though persona codes are not.

## Adding a persona

1. add the `PersonaDefinition` to `app/domain/persona.py`;
2. add its prompt pack under `app/prompts/` and register it in `app/prompts/oracle.py`;
3. add a `StatesGroup` in `app/bot/states.py` — aiogram identifies a state by its group
   class, so sharing one group would make two personas answer each other's updates;
4. add a `PersonaFlow` in `app/bot/persona_flows.py` and list it in `MVP_READING_FLOWS`;
5. add the menu entry in `app/bot/keyboards.py`.

No new use case, router, renderer or keyboard module is needed. A persona that needs a
deterministic symbol set supplies a `SymbolDrawer`.

A persona that needs its own intake or a calculation engine — the astrologer is the only
one today — keeps its own use case, router and renderer, but still reuses `ReadingFlow`
for the shared transport surface (namespace, result keyboards, history) and **must**
register a `SafetyIntake` so the crisis middleware covers it.

## Tests

- One test file per behavior, named after the module under test.
- Postgres-backed tests carry `@pytest.mark.postgres` and a `_postgres` file suffix.
- Parametrize over `MVP_READING_FLOWS` rather than asserting for one persona.
- The protected node IDs in `scripts/run_platform_invariants.sh` are a contract: a gate is
  never made green by deleting a node ID or loosening an assertion.
