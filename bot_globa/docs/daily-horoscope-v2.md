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
- the transit Moon sign determines the day's sector focus for each sign;
- one close relevant sky aspect supplies the common theme/action emphasis;
- output remains short enough for the Telegram daily-horoscope caption contract.

This is an astrology product convention, not a natal chart and not a scientifically validated prediction method. It must never be described as individualized astrology.

## Immutable daily snapshot

The first valid mass snapshot persisted for `forecast_date` becomes authoritative for that date.

The row stores:

- `forecast_date`;
- `sky_version`;
- `methodology_version`;
- canonical `sky_digest`;
- the complete rendered-content payload.

Concurrent workers use PostgreSQL `ON CONFLICT DO NOTHING` and then re-read the stored row. A worker restart or an application deploy during the day must therefore not silently change the digest already sent to earlier users.

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
