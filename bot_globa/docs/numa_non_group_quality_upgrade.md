# Numa non-group content quality upgrade

Scope: every audit finding except Telegram group scenarios.

Implemented in this change:

- Shared daily horoscope: one grounded LLM editorial pass per civil date, persisted once and reused for the audience.
- Daily grounding stays application-owned: calculated sky and solar-sign signals are inputs; the model cannot recalculate astronomy.
- Daily temporal anti-repetition: compare each sign and the shared theme against up to 60 previous published snapshots, with one repair attempt.
- Daily resilience: if the provider or validation fails, persist one deterministic fallback for the date instead of blocking the 08:00 delivery or retrying the provider per recipient.
- Same-sign temporal quality metrics complement the existing cross-sign benchmark.
- New versioned personal prompt packs add an explicit Numa editorial bar while old prompt versions remain loadable for persisted readings.
- Low-confidence `Расскажите Numa` routing now asks one explicit clarification instead of silently sending every unknown intent to Tarot.
- Completed-reading memory extraction has a first-class versioned prompt pack and a new extraction version.
- Offline editorial-quality helpers flag redundancy and stock phrasing without making runtime generation brittle.

Explicitly out of scope: every group game, compatibility flow and Astro Duel behavior.
