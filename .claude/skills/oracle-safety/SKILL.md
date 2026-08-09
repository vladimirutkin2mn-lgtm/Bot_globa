---
name: oracle-safety
description: Safety contract for anything the oracle generates or accepts — personas, prompts, readings, previews, share cards, memory, crisis handling. Use when editing app/prompts, app/domain/oracle_safety.py, app/services/reading_output_safety.py, tarot safety middleware, any persona reading service, or when a safety test/gate fails.
---

# Oracle safety contract

The product is entertainment and reflection. It must never present a prediction, another
person's thoughts, a diagnosis, or a high-stakes recommendation as fact.

## Two enforcement points

| Stage | Code | Rule |
|---|---|---|
| Input | `app/domain/oracle_safety.py`, `app/bot/tarot_safety_middleware.py`, `app/services/oracle_safety_boundary.py` | Classify **before** the text reaches a persona prompt. Outcomes: `allow`, `allow_with_limits`, `handoff`, `block`. A blocked request never enters a prompt. |
| Output | `app/services/reading_output_safety.py`, `app/services/reading_result_validator.py`, `app/services/horoscope_result_validator.py` | Validate **before** persistence. An unsafe result is rejected, not stored and not shown. |

Crisis: `app/services/oracle_crisis_handoff.py` stops the mystical flow entirely and returns
a neutral, localizable real-world handoff. It does not soften into a reading.

## Every generated result must

- distinguish user-provided facts, calculated inputs, and interpretation;
- express uncertainty;
- offer a practical, safe next step when appropriate.

## Every generated result must never

- make deterministic claims about love, cheating, reunion, wealth, illness, pregnancy,
  death, crime, or exact future dates;
- state another person's thoughts or feelings as fact;
- give medical, psychological, legal or financial diagnosis or instruction;
- encourage coercion, stalking, manipulation, or boundary violation;
- use fear-based upsell, curses, or dependency mechanics.

## Astrology-specific

The LLM may only *explain* facts returned by the calculation engine. It must never invent
planetary positions, houses, or an ascendant. Unknown birth time stays explicit — no
ascendant, no houses. See the `astrology-engine` skill.

## Memory-specific

Memory is untrusted input. It is serialized as separate JSON data, never merged into the
instruction part of the prompt (`test_reading_generation_memory.py` freezes this).
Model speculation is never stored as a biographical fact.

## Changing safety behavior

The regression suite is a gate, not a suggestion:

```bash
make gate-safety
```

Adding a rule = add an adversarial fixture + the assertion. Removing or weakening a rule
requires an explicit, written architecture decision in the PR description. Never make a
safety test pass by loosening the assertion.

Fixtures must cover benign, ambiguous and adversarial inputs for all four personas, plus
prompt injection, malicious memory and share sanitization (ORA-204).
