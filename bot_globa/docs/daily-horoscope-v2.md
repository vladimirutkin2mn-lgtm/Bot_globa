# Daily Horoscope v2

## Product contract

Daily Horoscope v2 separates two products that must not be confused:

1. **Mass daily horoscope** — the same twelve-sign digest for everyone on a civil date.
2. **Personal daily forecast** — an Astrologer reading calculated from the user's stored birth profile and that day's transits.

Neither path scrapes or copies a third-party horoscope website.

## Mass daily methodology

The application calculates a geocentric sky snapshot at 12:00 UTC with Astronomy Engine for the supported ten bodies:

- Sun
- Moon
- Mercury
- Venus
- Mars
- Jupiter
- Saturn
- Uranus
- Neptune
- Pluto

The snapshot also contains the supported major inter-planet aspects using the same bounded aspect family used elsewhere in the astrology domain.

The mass digest then applies a deliberately limited **solar-sign** convention:

- the reader's zodiac sign is treated as the first solar sector;
- one close relevant sky aspect supplies the shared theme of the day;
- for each zodiac sign, every transiting body is mapped into its whole-sign solar house;
- the most salient house/body/aspect combination is selected separately for that sign;
- supportive aspects produce opportunity-oriented language, tense aspects produce cautious language, and conjunctions produce a concentrated theme;
- astrology jargon stays under the hood: the user sees a short life-area prediction in plain Russian;
- output remains short enough for the Telegram daily-horoscope caption contract.

This means all users see the same theme and the same twelve forecasts for a date, but the twelve sign forecasts are no longer one global action copied across different house labels.

This is an astrology product convention, not a natal chart and not a scientifically validated prediction method. It must never be described as individualized astrology.

## Versioned daily snapshot

A valid mass snapshot persisted for `forecast_date` is reused while its sky and methodology versions are current.

The row stores:

- `forecast_date`;
- `sky_version`;
- `methodology_version`;
- canonical `sky_digest`;
- the complete rendered-content payload.

When the product methodology version changes, an older snapshot for the same date is regenerated and atomically replaced. Concurrent workers use a PostgreSQL upsert, so they converge on the same deterministic content for the current version. Ordinary worker restarts do not change a current-version digest.

## Personal daily forecast

The personal CTA uses the existing fact-bound Astrologer pipeline with the versioned scope:

`day_forecast__YYYY_MM_DD`

A personal day bundle contains:

- the user's existing calculated natal facts;
- one sampled transit snapshot for the anchored day;
- transit-to-natal aspects selected by the existing bounded fact service;
- the same fact digest, semantic validation and safety rules as other Astrologer readings.

The LLM may interpret only application-calculated facts. It does not calculate, correct or invent chart positions.

## Privacy and cost

The mass digest needs no birth data and no per-recipient LLM call. One stored snapshot is reused across the audience.

Personal forecasts use the already-consented encrypted birth profile and the existing Astrologer generation path. Mass content must never expose or depend on personal profile data.

## Analytics

Valid measurable funnel events are delivery, explicit screen/CTA interaction, personal forecast generation and downstream purchase/use. Telegram does not provide a reliable message-read receipt, so the product must not claim to measure `daily_read` merely because a message was delivered.
