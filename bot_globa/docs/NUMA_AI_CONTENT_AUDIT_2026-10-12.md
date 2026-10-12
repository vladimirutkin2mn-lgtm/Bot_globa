# Numa AI/content audit — 2026-10-12

## Executive summary

The product currently has two very different content architectures:

1. **Personal readings** (Tarot, Love Oracle, Internal Reflection, personal Astrology, reading follow-up) are genuine LLM flows with structured output, grounding, validation, repair and safety controls.
2. **Mass Daily and Group games** are mostly deterministic calculations plus small hard-coded copy libraries. They can look like AI experiences in Telegram, but no LLM narrator is involved in the main content path.

The biggest product-quality gaps are therefore not in the core personal prompts. They are:

- **P0 — Mass Daily:** repetitive copy is structurally guaranteed by a small phrase palette. Current quality benchmark measures cross-sign diversity in one batch but not same-sign repetition over 7/30/90 days.
- **P0 — Group Compatibility + Astro Duel:** deterministic calculations are useful and should remain authoritative, but result narration is template-driven and thin. Add a grounded LLM narrator after calculation; never let the LLM choose scores, cards, aspects or winners.
- **P1 — Personal Oracle routing:** `Расскажите Numa` uses regex routing, not an LLM classifier. This is auditable and cheap, but unknown intent falls back to Tarot and can misroute users. Measure routing quality before deciding whether a small structured classifier is justified.
- **P1 — Editorial quality/evals:** existing core prompts are strong on grounding and safety but relatively weak on explicit examples of the desired premium Numa voice. Add style/evaluation fixtures rather than simply making prompts longer.
- **P1 — Legacy group catalogue:** many hidden/typed group commands are deterministic novelty mechanics with hard-coded predictions/copy. Review whether they strengthen Numa or dilute the product before adding AI to them.

A useful design rule for the next iteration:

> **Calculation/rules decide facts; LLM decides language.**

Do not use an LLM for billing, safety gates, eligibility, astronomical calculations, card selection, group winners, scores or scheduling. Use it where interpretation, narrative variety and human-quality wording are the product.

---

## 1. Actual LLM call graph

The main Telegram runtime builds one observed LLM client in `app/bot/main.py`. It is wired into:

- `ReadingGenerationService` — Tarot, Love Oracle, Mystical Psychologist;
- `HoroscopeGenerationService` — personal Astrology;
- `ReadingFollowUpService` — follow-up questions on an existing reading.

A separate `oracle_memory` worker creates an LLM client for structured memory extraction from completed readings.

The current `app/prompts/` package contains prompt packs for:

- `tarot-reader-v4`;
- `love-oracle-v2`;
- `mystical-psychologist-v2`;
- `astrologer-v2`;
- `reading_followup_v1`.

There is no Daily or Group prompt pack in production today.

---

## 2. Surface-by-surface audit

| Surface | User-visible AI? | Actual engine | LLM? | Current assessment | Recommendation |
|---|---|---|---|---|---|
| Main menu / onboarding / consent | No need | Rules/UI | No | Good | Keep deterministic |
| `Расскажите Numa` routing | Feels intelligent | Regex intent router | No | 6.5/10 | P1 routing eval; LLM classifier only if needed |
| Tarot | Yes | Deterministic card draw + LLM interpretation | Yes | 9/10 | Keep architecture; add style/evals |
| Love Oracle | Yes | Structured LLM | Yes | 8.5/10 | Keep; add editorial examples/evals |
| Internal Reflection | Yes | Structured LLM | Yes | 8.5/10 | Keep; add editorial examples/evals |
| Personal Astrology | Yes | Natal/transit calculation + grounded LLM | Yes | 9/10 | Keep |
| Personal daily CTA | Yes | Reuses personal Astrology path | Yes | 9/10 architecture | Keep |
| Reading follow-up | Yes | Existing structured reading + grounded LLM | Yes | 9/10 | Keep |
| Reading memory extraction | Invisible | Structured extractor | Yes | 8/10 | Version/editorial policy review |
| Reading memory retrieval | Invisible | Deterministic ranking | No | Good | Keep deterministic |
| Safety/crisis handoff | Invisible | Deterministic classifier/handoff | No | Good | Keep before LLM |
| Mass daily horoscope | Looks generative | Astronomy + phrase rotation | **No** | **3/10 content** | **P0 grounded daily editor + anti-repeat** |
| Daily share card | Looks fresh | Reuses mass Daily theme | No extra call | Inherits Daily problem | Fix Daily source; card renderer can stay |
| Group Compatibility — natal | Looks interpretive | Synastry calculation + template | **No** | **4–5/10 content** | **P0 grounded narrator** |
| Group Compatibility — quick signs | Looks interpretive | Element/modality formula + template | **No** | 4/10 | Narrator optional but useful; label as quick mode |
| Astro Duel | Looks like AI commentary | Transit scoring + deterministic winner + template | **No** | **4–5/10 content** | **P0 grounded commentator** |
| Group `/card`, `/event`, `/party` | Clearly game-like | Stable hash/cards/templates | No | 6/10 as party toys | LLM not required |
| Legacy group social mechanics | Game-like | Hash + hard-coded copy | No | Mixed | P1/P2 prune before expanding |
| Personal reading share | Yes, derived | Uses validated `share_card` from original LLM result | No extra call | Good | Keep |
| Payments / subscription / refund / settings | No | Deterministic services | No | Correct | Never add LLM |

---

## 3. Core personal prompts

### 3.1 Tarot — `tarot-reader-v4`

**What is good**

- Application owns the selected Rider-Waite-Smith card data.
- The LLM cannot replace card IDs, orientations or positions.
- The prompt explicitly asks for spread synthesis instead of three independent definitions.
- Reversed cards must use supplied orientation meaning rather than naive inversion.
- Memory is optional and current input has priority.
- Output is strict JSON and then semantically validated against the selected cards.

**Main weakness**

The prompt is strong as an engineering contract but has almost no positive exemplars of exceptional Numa prose. It says many things the model must not do, but gives less guidance on the difference between acceptable and memorable output.

**Recommendation**

Keep `v4` as the grounding contract. Create an editorial `v5` only after an eval set exists. Add examples/evals for:

- direct opening that answers the question;
- spread-level synthesis;
- low generic-advice rate;
- non-repetitive practical steps;
- premium, concise Russian voice;
- rendered Telegram preview quality, not only raw JSON quality.

### 3.2 Love Oracle — `love-oracle-v2`

**What is good**

- Explicitly answers emotional questions instead of hiding behind generic “we cannot know another person” language.
- Still forbids treating another person's inner state as known fact.
- Good focus on observable signals, ambiguity, initiative and distance.
- Avoids therapy clichés and manipulation.

**Weakness**

No few-shot style examples and no explicit repetition/genericness scoring. The model can still repeatedly use the same relationship vocabulary while remaining fully schema-valid and safe.

**Recommendation**

Keep architecture. Add editorial evals and a small set of gold examples. Do not add more safety boilerplate to the user-visible result.

### 3.3 Internal Reflection — `mystical-psychologist-v2`

**What is good**

- Clear boundary: archetypal metaphor, not diagnosis or therapy.
- Requires a central conflict/loop and a practical experiment.
- Discourages default journaling and generic coaching.

**Weakness**

Same editorial problem: correctness is better specified than voice. Also monitor whether the name/voice drifts too close to clinical psychology.

**Recommendation**

Keep engine. Add tests for distinct archetypal lenses, non-clinical language and practical-step diversity.

### 3.4 Personal Astrology — `astrologer-v2`

This is the best reference architecture in the product.

Pipeline:

`calculated natal/transit facts -> FACT_BUNDLE_JSON -> LLM interpretation -> fact-id validation -> renderer`

The prompt makes `FACT_BUNDLE_JSON` the only permitted source of astrology facts and prohibits recomputation or invention. The renderer resolves labels from application facts again.

**Recommendation**

Use this pattern as the model for Daily and Group improvements.

### 3.5 Reading follow-up — `reading_followup_v1`

Strong grounding. The follow-up cannot create new cards, planets or events; it can only explain the existing structured reading and must attach conclusions to permitted reading references.

**Recommendation:** keep.

---

## 4. `Расскажите Numa`: intelligent UX, deterministic router

`personal_oracle_handlers.py` does not call an LLM to choose a practice. It uses regular expressions for work, love, reflection, decisions and relationship ambiguity. Unknown/default intent becomes Tarot/general forecast.

This is not automatically a defect: a deterministic router is cheap, fast, testable and predictable. The problem is the current fallback bias.

### Risks

- A question outside the regex vocabulary can silently become Tarot.
- Mixed love/reflection/work situations require brittle keyword combinations.
- The user sees “Numa understood…” even though understanding is a ruleset.

### Recommendation — P1

Build a routing eval corpus first (100–300 realistic Russian questions, including slang, typos and mixed intents). Measure:

- target persona accuracy;
- clarification rate;
- false Tarot fallback rate;
- rescue feedback `Не про мой вопрос` by route.

Only if the deterministic router materially underperforms, replace/augment it with a tiny structured classifier returning one of a closed enum plus confidence. Do not use a free-form generation call for routing.

---

## 5. Mass Daily: main content P0

### Current architecture

`daily_sky.py` calculates a real deterministic sky snapshot and selects a daily driver/topic. That part is useful.

The user-visible copy is then built from finite hard-coded phrase libraries in `daily_sky.py` and `daily_horoscope_editorial.py`. Selection is deterministic and rotates by date/sign/topic.

This means recurrence is **structural**, not an LLM quality accident.

Examples currently hard-coded include phrases seen repeatedly in production Telegram history:

- `не стоит форсировать то, что просит точной настройки`;
- `напряжение покажет, что пора изменить`;
- `Инициатива заметна — заранее выберите цель.`

The `инициатива` story bucket contains only six variants. Other buckets frequently contain four variants.

### Why the current benchmark did not catch it

`daily_horoscope_benchmark.py` measures useful metrics such as cross-sign lexical diversity, opening uniqueness, topic coverage and actionable ratio for a batch of 12 signs.

It does **not** measure the user's actual retention experience:

- same sign over 7 days;
- same sign over 30 days;
- same sign over 90 days;
- repeated headline/central advice;
- near-duplicate phrasing across dates.

Thus an implementation can pass the current benchmark while looking obviously repetitive in Telegram search.

### Recommended target architecture — P0

`astronomy -> deterministic structured daily facts -> one batched LLM editor per date -> validator -> persisted snapshot`

The LLM must never invent or change sky facts. Generate one daily batch, not one call per subscriber:

- one common day theme;
- 12 sign forecasts;
- optional share headline.

Persist the result as the existing date snapshot and reuse it for all sends.

### Required anti-repetition gates

Before accepting a new snapshot compare each sign with at least the last 30–60 days:

1. exact normalized-text hash;
2. repeated opening/headline;
3. token/Jaccard overlap;
4. repeated core action/advice;
5. optionally embedding/semantic similarity if available cheaply.

If similarity exceeds threshold, regenerate only the offending entries using the same fact bundle plus recent-copy exclusions.

Add longitudinal evals for 7/30/90 day windows. This is more important than further tuning the existing cross-sign benchmark.

### Personal daily is different

The CTA from Daily into the personal “what matters for me today” experience reuses the normal personal Astrology generation path. That path is already LLM-backed and grounded in natal/transit facts. Do not rewrite it together with mass Daily.

---

## 6. Group product: deterministic core, missing narrative layer

The group code explicitly states that the group layer does not call the LLM. This was a privacy/retry design decision, not an accidental missing dependency.

That is appropriate for **selection and calculation**, but too restrictive for the two primary games where interpretation is the user value.

### 6.1 Compatibility — P0

Precise mode:

`two consented natal charts -> calculate_synastry -> scores/aspects -> Python renderer`

Quick mode:

`two self-selected Sun signs -> element/modality formula -> scores -> static renderer`

The calculations should remain deterministic. The result language should not.

**Target:**

`calculation -> GroupCompatibilityFacts -> grounded LLM narrator -> strict validator -> Telegram`

Schema should include application-owned fields copied exactly, for example:

- context (`love/friendship/work/travel`);
- overall / attraction / communication / long-term scores;
- strongest supports;
- strongest tension;
- precision mode (`natal` or `sun_sign_quick`);
- selected card ID/theme if card remains part of game.

LLM returns only narrative fields such as:

- headline;
- 2–3 sentence synthesis;
- strongest dynamic explanation;
- tension explanation;
- playful practical “pair tip”.

Validator rejects any changed score, aspect, card, precision label or participant fact.

### 6.2 Astro Duel — P0

Current three rounds are deterministic Mars/Moon/Venus scores. Winner and tie-break are application-owned. Reasons are formula strings.

Keep all of that. Add an LLM as **commentator**, not referee.

Target output:

- one short opening;
- one lively sentence per round grounded in the provided reason/score;
- final winner line;
- playful closing.

The model must not change winner, score or round order.

### 6.3 Casual/legacy group games — do not blindly add LLM

The shipped runtime still installs a large catalogue behind the compact menu. Typed/secondary mechanics include variants of:

- card/day;
- couple;
- seance;
- Tarot yes/no;
- cosmic advice;
- party/event;
- chat forecast;
- roles/cards/versus/karma/week.

Most are stable hashes, deterministic Tarot selection or small hard-coded text pools.

For these, the first question is not “how do we add an LLM?” but “should this mechanic remain in Numa?”. Several strings (`спиритический сеанс`, deterministic “предсказание дня”, generic after-midnight predictions) feel more like an old viral bot than the current calmer Numa brand.

**P1/P2 recommendation:** prune or explicitly classify secondary party toys before investing in generation quality. Keep the visible menu focused on Compatibility and Astro Duel.

---

## 7. Memory

### Extraction

A background worker uses `LLMReadingMemoryExtractor` on completed readings after explicit memory consent. It extracts structured candidates and marks epistemic basis as `user_stated` or `model_inferred`.

Architecture is good, but the system prompt is embedded in the service rather than managed as a first-class prompt pack. The extraction version exists, but prompt evolution should be easier to audit.

**P1 recommendation:** move the extraction prompt into a versioned prompt pack and add an eval set for over-memory, wrong provenance and sensitive/transient information.

### Retrieval

Memory selection for new readings is deterministic: topic/kind weights, token overlap, confidence and staleness. This is good. Do not add a second LLM just to select memory unless offline evaluation proves the current ranker inadequate.

---

## 8. Safety

The safety middleware classifies user-authored intake before it reaches persona persistence or LLM generation. Crisis handoff is deterministic.

This is the correct place **not** to add creative generation.

Keep safety, billing, entitlement, payment and schedule decisions outside the LLM.

---

## 9. Sharing

### Personal reading share

No separate share-generation call is made. The personal LLM result already contains a validated anonymous `share_card`; the share handler owner-checks the reading and exports only that payload.

Architecture is sound.

### Daily share

Daily share uses only the mass Daily date/theme and therefore inherits the Daily repetition problem. The image/rendering pipeline can remain unchanged after the Daily content source is improved.

---

## 10. Validation and eval gap

The personal reading pipeline validates:

- JSON shape;
- exact symbol IDs/positions/orientations;
- safety semantics;
- presentation limits;
- optional one-shot repair.

What it does **not** currently validate strongly enough is editorial quality:

- genericness;
- repeated sentence structures;
- repeated practical advice;
- persona voice drift;
- similarity to recent answers;
- quality of the rendered Telegram preview.

A valid safe JSON object can still be a mediocre product answer.

### Proposed eval layers

**Layer A — structural (existing):** schema, IDs, fact references, safety.

**Layer B — editorial:** specificity, directness, usefulness, Numa voice, low cliché rate.

**Layer C — longitudinal:** repetition across the same user/sign/topic over time.

**Layer D — rendered UX:** judge exactly what Telegram displays after preview/full renderer truncation.

---

## 11. Prioritized implementation plan

### P0.1 — Rebuild mass Daily content layer

- keep astronomical calculation;
- create structured daily fact bundle;
- add `daily-editor-v1` prompt pack;
- generate one batch/day;
- validate facts + output schema;
- persist snapshot;
- add 7/30/90-day anti-repeat tests and gates;
- preserve current share-card and scheduling contracts.

### P0.2 — Add grounded group narrators

- `group-compatibility-v1` prompt/schema/validator;
- `group-duel-v1` prompt/schema/validator;
- keep all scores/aspects/cards/winners application-owned;
- add graceful deterministic fallback if LLM unavailable;
- benchmark latency because group games must remain fast.

### P1.1 — Build prompt/editorial eval suite for personal readings

Create a curated Russian scenario set per persona with expected qualitative dimensions. Evaluate the **rendered** result.

### P1.2 — Routing quality

Create realistic corpus for `Расскажите Numa`; measure route accuracy and false Tarot fallback. Only then decide on an LLM classifier.

### P1.3 — Version memory extraction prompt

Move embedded prompt into prompt registry and add provenance/over-memory evals.

### P1.4 — Clean secondary group catalogue

Decide which legacy mechanics belong in current Numa. Remove/hide low-value gimmicks before polishing them.

### P2 — Editorial polish

After evals exist, consider new prompt versions with a small gold-example style pack rather than adding more prohibitions.

---

## 12. Acceptance criteria for the next content architecture

The next iteration should satisfy all of these:

1. No user-facing astrology fact is invented by an LLM.
2. No group score/card/winner is chosen by an LLM.
3. Daily does not repeat exact headline, central sentence or practical action for the same sign inside the configured recent-history window except an explicit validated fallback.
4. Compatibility and Duel remain usable if the LLM provider is unavailable; deterministic facts still render safely.
5. Personal persona prompt versions remain immutable/versioned.
6. Every generative result is judged after the Telegram renderer, not only as raw JSON.
7. Product analytics can distinguish generation fallback vs LLM narration success without logging private content.
8. Secondary group mechanics are not promoted merely because they exist in code.

## Final assessment

Numa is not “mostly fake AI”. The core paid/personal product is genuinely LLM-backed and has unusually solid grounding and validation. The inconsistency is at the product edges that are important for growth and retention: **Daily and Groups look like generative Numa experiences but are still largely finite template systems.**

The next engineering work should therefore focus less on adding more features and more on making the highest-frequency surfaces use the same architecture quality already present in personal Astrology: deterministic facts first, bounded LLM interpretation second, validation third, and explicit longitudinal quality gates.