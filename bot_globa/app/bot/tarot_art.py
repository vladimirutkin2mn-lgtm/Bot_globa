"""Resolve the illustration for a drawn Rider-Waite-Smith Tarot card.

The whole 78-card deck is a bundled asset, exactly like every other image the bot sends:
22 bespoke Major Arcana plus the public-domain Smith 1909 Minor Arcana. Nothing here
reaches the network, so a card cannot silently stop rendering because a third-party host
went away, and the production image carries everything the reveal needs.

Naming and the acceptance rules for the images themselves are in
`docs/tarot-card-assets.md`.
"""

from functools import cache
from pathlib import Path

from app.bot.scene_media import Art
from app.domain.tarot import RWS_78_V1

TAROT_ASSET_DIR = Path(__file__).parent / "assets" / "tarot"

_RWS_CODES = frozenset(card.code for card in RWS_78_V1.cards)


@cache
def card_art(symbol_id: str) -> Art | None:
    """Return exact card art for a known RWS symbol, never a generic substitute.

    The symbol id is the card's own code from the catalogue, so the file name is the only
    thing binding a picture to a meaning — `major_13.jpg` has to be Death because
    `TarotCard("major_13", "Смерть", …)` says so. An unknown code answers `None` rather
    than reaching for a file path built out of caller-supplied text.
    """

    if symbol_id not in _RWS_CODES:
        return None

    path = TAROT_ASSET_DIR / f"{symbol_id}.jpg"
    if not path.is_file():
        return None
    return Art(key=f"tarot:{symbol_id}", path=path)


def deck_is_installed() -> bool:
    """Whether the bundled deck is present at all; used by tests and diagnostics."""

    return TAROT_ASSET_DIR.is_dir() and any(TAROT_ASSET_DIR.glob("major_*.jpg"))
