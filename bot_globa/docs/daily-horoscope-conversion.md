# Daily Horoscope conversion loop

## Product path

The common daily horoscope is the free retention surface. Its primary paid-growth path is
now explicit:

`daily digest -> personal forecast CTA -> Astrologer -> day_forecast -> preview -> checkout -> purchase`

The daily digest does not promise that the mass forecast is personal. The footer explains
the incremental value in one line: the personal forecast uses the user's natal chart and
today's calculated transits.

The Astrologer puts `day_forecast` first so the CTA does not land on a generic six-choice
menu with the intended continuation hidden below other topics.

## Measurement

Telegram does not expose a bot-message read receipt. We therefore do **not** manufacture an
"open" or "read" metric.

Use observable signals instead:

1. `daily_horoscope_delivered` structured worker log — aggregate count of confirmed sends;
2. `persona_selected` with `persona_code=astrologer` and `topic_code=day_forecast` — existing
   privacy-safe product event for users who enter the personal-daily path;
3. `reading_started` / `reading_preview_ready` with the same persona/topic — existing reading
   funnel;
4. `checkout_started` — existing billing funnel;
5. `purchase_completed` — existing billing funnel.

The first useful conversion ratio is therefore personal-daily starts divided by confirmed
daily deliveries. Preview, checkout and purchase conversion are then measured downstream
with the existing events.

User-level D1/D7/D30 retention should be calculated on the existing privacy-safe internal
analytics subject for users who start a `day_forecast`, not from Telegram identifiers or
birth data. A dedicated user-level `daily_horoscope_delivered` analytics event is intentionally
not added in this change: the current analytics taxonomy has no such event and extending it
should be a separate privacy-reviewed contract change rather than bypassing the allow-list.

## Intraday "best window"

No hour-of-day window is displayed yet. The mass horoscope calculation currently uses one
geocentric noon-UTC sky snapshot for the civil date. That supports a day theme and solar-sign
story, but it does not support a defensible claim such as "best time 14:00-16:00". Adding an
hour would therefore create false precision.

If an intraday window is added later, it must come from an explicit time-resolved transit
calculation and have regression coverage for timezone/date boundaries.
