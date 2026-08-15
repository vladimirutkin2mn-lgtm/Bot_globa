# Tarot domain v2: Rider–Waite–Smith baseline

## Product decision

New Tarot readings use the Rider–Waite–Smith (RWS) tradition as one explicit, versioned baseline instead of asking the language model to supply Tarot knowledge from its own training.

This is a symbolic/divinatory tradition used for an entertainment and reflection product. It is not treated in the application as a scientifically validated method of predicting external events.

## Source basis

The domain model was built against primary/historical descriptions of the Waite tradition, especially A. E. Waite's *The Pictorial Key to the Tarot* (1910), together with museum documentation of Tarot deck structure and the Smith–Waite deck.

The implementation paraphrases meanings into compact Russian application data. It does not reproduce source passages verbatim.

Waite documents general divination layouts, including the Celtic method, but does not define a canonical modern set of separate "love", "work", "decision" or "repeating pattern" spreads. The topic-specific layouts below are therefore explicitly **product-owned RWS layouts**: RWS supplies the card tradition, while Numa owns the role assigned to each position.

## Deck contract

`rws-78-v1` contains the full 78-card structure:

- 22 Major Arcana;
- 56 Minor Arcana;
- four suits: Wands, Cups, Swords and Pentacles;
- each Minor suit has Ace through Ten plus Page, Knight, Queen and King.

Every card stores:

- stable card code and Russian display name;
- Major/Minor classification;
- suit and rank for Minor Arcana;
- explicit upright meaning;
- explicit reversed meaning;
- a compact symbolic focus.

Suit and rank semantics are also application-owned and versioned.

## Interpretation contract

The LLM no longer receives only a card name and a one-line generic hint. For every selected card the application builds bounded knowledge containing:

- `tradition`;
- `arcana`;
- `position_focus`;
- `orientation_meaning`;
- `symbolic_focus`;
- `suit` and `suit_focus` for Minor Arcana;
- `rank` and `rank_focus` for Minor Arcana.

`tarot-reader-v4` must treat this payload as authoritative. It may synthesize and express the spread naturally, but it may not invent alternative card meanings or add unsupplied astrological, Kabbalistic, elemental or numerological correspondences.

Reversed cards use an explicit reversed interpretation. They are not produced by mechanically negating the upright meaning.

## Reading heuristic

The interpretation is expected to work at three levels:

1. **Card in position.** What this exact card contributes to the role it occupies in the spread.
2. **Relationships between cards.** Reinforcement, contrast, transition or a repeated motif across the spread.
3. **Answer to the question.** A coherent reading of the user's concrete situation rather than independent dictionary entries.

Major Arcana may be treated as broader archetypal pressure and Minor Arcana as more situational texture when that distinction helps the reading, while all concrete claims remain bounded by the application-provided card data.

## Topic-specific spread contract

A new Tarot draft selects one spread from its explicit topic and immediately persists the chosen stable code as `Reading.symbol_set_code`. The topic router is used **only at draft creation**. Retry, worker replay and process restart load the persisted code instead of asking the current router to choose again.

Current layouts are five-card, versioned product layouts:

| Topic | Spread code | Positions |
|---|---|---|
| Relationships | `relationship_five_v1` | current relationship dynamic; bond/attraction; distance/friction; unspoken factor; direction under current conditions |
| Work and money | `work_five_v1` | current work situation; opportunity; constraint; available resource; next step |
| Choice | `decision_five_v1` | core of the decision; option A potential; option A cost; option B potential; option B cost |
| Repeating pattern | `pattern_five_v1` | trigger; hidden need/motive; reinforcement; break point; alternative response |
| Open question | `open_question_five_v1` | central theme; emerging influence; fading influence; blind spot; near-term direction under current conditions |

The position descriptions deliberately preserve product safety boundaries. For example, an "unspoken factor" can describe ambiguity, behavior or an unobserved dynamic, but does not authorize factual claims about another person's private thoughts or feelings. A direction position describes a conditional trajectory rather than a guaranteed future.

Legacy `three_card_v1` and `one_card_v1` remain resolvable for historical readings and tests; they are not silently remapped to a newer layout.

## Visual card contract

The reveal must show the exact card selected by the deterministic engine; a generic scene image is not an acceptable substitute for a known RWS card.

- The existing 22 bespoke Major Arcana illustrations remain local under `app/bot/assets/tarot/` to preserve the product's dark Numa visual language.
- Minor Arcana use public-domain Rider–Waite imagery from the `mixvlad/TarotCards` mirror.
- The runtime source is pinned to upstream revision `5c44ca5c94a9d67f9bc06cb6b920c2544fa76c74`, never to a moving `main` URL.
- Card IDs are mapped by application-owned suit/rank tables; arbitrary symbol IDs cannot become external URLs.
- Telegram's returned `file_id` is cached under the same stable `tarot:<symbol_id>` key after a successful first send.
- If Telegram cannot fetch or accept a card image, the reading still degrades to text rather than failing.

This remote fallback is a deployment trade-off, not domain knowledge. A future fully bespoke 78-card art pack can replace the URLs without changing `rws-78-v1`, the draw engine or the interpretation prompt.

## Versioning and replay

Legacy `tarot-major-v1`, older prompt packs and historical reading versions remain in the repository so previously persisted readings are reproducible.

New Tarot readings use:

- catalog: `rws-78-v1`;
- engine: `tarot-symbolic-v2`;
- prompt: `tarot-reader-v4`;
- result schema: `reading-result-v1`;
- persisted spread contract: `Reading.symbol_set_code`.

The deterministic draw is seeded by the reading ID, engine version, catalog version and persisted spread code, so retries of the same reading produce the same positions, cards and orientations.

The migration introducing `symbol_set_code` backfills all Tarot readings produced by earlier `tarot-symbolic-v1` / `tarot-symbolic-v2` deployments to `three_card_v1`, because that was the only Tarot layout available before topic-specific routing existed. Non-symbolic personas retain `none`.
