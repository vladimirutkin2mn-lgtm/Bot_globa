---
name: astrology-engine
description: Horoscope and natal chart work — BirthProfile intake, the deterministic Astrology Calculation Engine, fact-bound horoscope generation and the tarot Symbolic Engine. Use when touching app/services/natal_chart.py, birth_profile, horoscope_*, symbolic_engine.py, app/domain/natal_chart.py, or when a chart/tarot determinism test fails.
---

# Calculation engines

Two deterministic engines sit **outside** the LLM. The LLM only explains what they return.

## Astrology Calculation Engine

`app/services/natal_chart.py`, `app/domain/natal_chart.py`, backed by `astronomy-engine`
(pinned `==2.1.19`) and `tzdata` (pinned). Both pins are part of the contract — a version
bump changes computed output and must be treated as a versioned engine change with
refreshed fixtures.

Rules:

- Same normalized input ⇒ byte-identical versioned payload. Normalization (place, timezone,
  DST) happens once, before calculation.
- **Unknown birth time ⇒ local noon, and no ascendant and no houses.** This is never
  softened, and the limitation is shown to the user.
- The result is versioned and carries provenance. Store the engine version with the reading.
- A ready reading replays from its stored fact bundle: no recalculation, no LLM call. A
  tampered fact bundle is rejected (`test_horoscope_generation.py`).

The LLM receives only the calculated fact payload. `horoscope_result_validator.py` rejects
any output that changes a planetary position, house or ascendant, or that presents a
forecast as a guaranteed event. Do not "fix" a validator failure by relaxing the validator.

BirthProfile is encrypted, consent-gated, and cascades on account deletion — see
`privacy-encryption`.

## Symbolic Engine (tarot)

`app/services/symbolic_engine.py`. Versioned card catalog, seeded from `reading_id`:

- one reading ⇒ one spread, stable across LLM retries, worker replays and webhook retries;
- positions and upright/reversed are part of the seeded draw, not a later random choice;
- the LLM interprets the drawn symbols; it never chooses or renames them.
  Symbol IDs in the structured result are validated against the drawn spread.

## Proof

```bash
pytest tests/test_natal_chart.py tests/test_horoscope_generation.py \
       tests/test_horoscope_reading.py tests/test_horoscope_renderer.py
make test-postgres        # chart + birth profile consent/deletion paths
make gate-safety
```

Changing a catalog or an engine ⇒ bump its version, keep old versions readable for stored
readings, and add fixtures for the new version. Never mutate an existing version in place.
