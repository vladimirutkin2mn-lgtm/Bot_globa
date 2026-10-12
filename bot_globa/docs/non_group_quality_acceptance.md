# Acceptance criteria: Numa non-group content quality

1. Daily horoscope
   - astronomy remains application-calculated;
   - one shared editorial LLM result is persisted per civil date;
   - same-sign copy is checked against up to 60 previous snapshots;
   - at most one repair attempt is allowed;
   - provider/validation failure falls back to one persisted deterministic snapshot;
   - no LLM request is made per recipient.
2. Personal readings
   - new readings use new frozen prompt versions with an explicit editorial-quality standard;
   - old prompt versions remain loadable for persisted readings;
   - quality heuristics are offline signals and never discard a safe reading at runtime.
3. Personal oracle router
   - strong intents remain deterministic and fast;
   - genuinely low-confidence input asks one clarification instead of silently defaulting to Tarot;
   - users can explicitly choose Tarot from that clarification.
4. Memory
   - completed-reading extraction runs through a first-class versioned prompt pack;
   - user-stated and model-inferred claims remain distinct.
5. Group scenarios
   - no group scenario behavior is changed by this work.
