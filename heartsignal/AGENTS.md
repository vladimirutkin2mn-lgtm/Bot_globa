# AGENTS.md — Bot Globa

## Mission

Migrate the imported HeartSignal production baseline into a Telegram-first personalized AI-oracle platform while preserving its mature billing, privacy, delivery, observability and release controls.

The planned MVP has four directions:

1. Tarot reader;
2. Love Oracle;
3. Mystical Psychologist;
4. Horoscope / Astrologer backed by a real calculation engine.

The product is an entertainment and reflective experience. It must not present predictions, another person's thoughts, diagnoses or high-stakes recommendations as facts.

## Sources of truth

Read in this order before changing code:

1. repository-level `docs/FABRIC_BOT_ADAPTATION_PLAN.md`;
2. repository-level `docs/MVP_BACKLOG.md`;
3. `docs/platform-core-boundaries.md`;
4. existing code and tests;
5. legacy `PRODUCT_SPEC.md` and `TASKS.md` only for current HeartSignal behavior and historical invariants.

The legacy product documents do not define the future oracle scope. When documents conflict, the repository-level oracle plan wins.

## Migration rules

- Implement one ORA task or one narrow vertical slice at a time.
- Do not combine code extraction, platform refactoring and product behavior changes in one pull request.
- Preserve existing Alembic revision IDs, financial ledger keys and provider idempotency keys.
- Add new migrations; never rewrite applied migrations.
- Characterize billing, privacy and delivery behavior before refactoring it.
- Keep external services behind interfaces: LLM, payments, astrology calculations, analytics and storage.
- Future domain code may depend on platform interfaces; platform modules must not depend on persona-specific code.
- Centralize runtime identity in `app.platform.identity`.
- Keep secrets and private user content out of logs, analytics and error metadata.

## Default technical direction

- Python 3.12;
- FastAPI;
- aiogram 3;
- PostgreSQL;
- SQLAlchemy 2 async and Alembic;
- Pydantic 2;
- pytest, Ruff and mypy;
- Docker Compose;
- provider-neutral `LLMClient`;
- a separate deterministic Symbolic Engine for Tarot;
- a separate versioned Astrology Calculation Engine for birth-chart facts.

## Product safety rules

Every generated result must:

- distinguish user-provided facts, calculated inputs and interpretation;
- express uncertainty;
- avoid deterministic claims about love, cheating, return, wealth, illness, pregnancy, death, crime or exact future dates;
- avoid medical, psychological, legal and financial diagnosis or instruction;
- avoid coercion, stalking, manipulation and violation of boundaries;
- avoid fear-based upsells, curses and dependency mechanics;
- provide a practical, safe next step when appropriate;
- stop the mystical flow and show a real-world handoff in crisis scenarios.

For astrology, the LLM may explain only facts returned by the calculation engine. It must never invent planetary positions, houses or an ascendant. Unknown birth time must remain explicit.

## Privacy defaults

- Encrypt sensitive questions, context, birth data and full results.
- Store compact long-term memory only with explicit consent.
- Never save model speculation as a biographical fact.
- Allow deletion of one reading, one memory item, a birth profile or all user data.
- Preserve immutable financial audit records while removing personal content.
- Never use user content for training by default.

## Definition of done

A task is complete only when:

1. its acceptance criteria pass;
2. formatting, linting, strict type checks and tests pass;
3. Alembic upgrade/downgrade/upgrade passes when migrations change;
4. Docker Compose configuration and production image build remain valid;
5. errors have safe user-facing behavior;
6. documentation reflects architectural decisions;
7. billing, privacy and release invariants are not weakened.
