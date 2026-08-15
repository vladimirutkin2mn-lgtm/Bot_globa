# Tarot domain v2: Rider–Waite–Smith baseline

## Product decision

New Tarot readings use the Rider–Waite–Smith (RWS) tradition as one explicit, versioned baseline instead of asking the language model to supply Tarot knowledge from its own training.

This is a symbolic/divinatory tradition used for an entertainment and reflection product. It is not treated in the application as a scientifically validated method of predicting external events.

## Source basis

The domain model was built against primary/historical descriptions of the Waite tradition, especially A. E. Waite's *The Pictorial Key to the Tarot* (1910), together with museum documentation of Tarot deck structure and the Smith–Waite deck.

The implementation paraphrases meanings into compact Russian application data. It does not reproduce source passages verbatim.

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
3. **Answer to the question.** A coherent reading of the user's concrete situation rather than three independent dictionary entries.

Major Arcana may be treated as broader archetypal pressure and Minor Arcana as more situational texture when that distinction helps the reading, while all concrete claims remain bounded by the application-provided card data.

## Versioning and replay

Legacy `tarot-major-v1`, older prompt packs and historical reading versions remain in the repository so previously persisted readings are reproducible.

New Tarot readings use:

- catalog: `rws-78-v1`;
- engine: `tarot-symbolic-v2`;
- prompt: `tarot-reader-v4`;
- result schema: `reading-result-v1`.

The deterministic draw is still seeded by the reading ID, engine version, catalog version and spread code, so retries of the same reading produce the same cards and orientations.

## Spread scope in this release

This version deliberately keeps `three_card_v1`:

- `current_influence`;
- `hidden_factor`;
- `next_step`.

Topic-specific spreads are a separate domain change. Before adding them, the chosen spread must itself be frozen/persisted as part of the reading contract so a retry or worker replay can never switch the spread after a draft has been created.

This separation gives the product a full Tarot knowledge layer now without coupling it to an unsafe migration of existing Reading replay semantics.
