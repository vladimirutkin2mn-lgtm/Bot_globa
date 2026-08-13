"""The illustration for a drawn tarot card, when the deck is installed.

The deck is an asset, not a dependency: the reveal is meaningful as text, and a missing
or partial `assets/tarot/` must degrade to the scene illustration rather than break a
reading. Everything here therefore answers `None` instead of raising, and the answer is
resolved once per process because the filesystem does not change under a running bot.

Naming and the acceptance rules for the images themselves are in
`docs/tarot-card-assets.md`.
"""

from functools import cache
from pathlib import Path

from app.bot.scene_media import Art

TAROT_ASSET_DIR = Path(__file__).parent / "assets" / "tarot"


@cache
def card_art(symbol_id: str) -> Art | None:
    """The picture for this card, or None when the deck does not carry it.

    The symbol id is the card's own code from the catalogue, so the file name is the only
    thing binding a picture to a meaning — `major_13.jpg` has to be Death because
    `TarotCard("major_13", "Смерть", …)` says so.
    """

    path = TAROT_ASSET_DIR / f"{symbol_id}.jpg"
    if not path.is_file():
        return None
    return Art(key=f"tarot:{symbol_id}", path=path)


def deck_is_installed() -> bool:
    """Whether any card art is present at all; used by tests and diagnostics."""

    return TAROT_ASSET_DIR.is_dir() and any(TAROT_ASSET_DIR.glob("major_*.jpg"))
