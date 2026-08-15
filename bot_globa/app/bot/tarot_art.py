"""Resolve the illustration for a drawn Rider-Waite-Smith Tarot card.

The product keeps its existing 22 bespoke Major Arcana assets locally. Minor Arcana use a
public-domain Rider-Waite image mirror pinned to an immutable upstream Git commit. Telegram
caches the resulting `file_id`, so the remote URL is needed only for the first successful
send of a given card in a running deployment.
"""

from functools import cache
from pathlib import Path

from app.bot.scene_media import Art
from app.domain.tarot import RWS_78_V1, TarotArcana

TAROT_ASSET_DIR = Path(__file__).parent / "assets" / "tarot"
RWS_ART_REVISION = "5c44ca5c94a9d67f9bc06cb6b920c2544fa76c74"
RWS_ART_BASE_URL = (
    "https://raw.githubusercontent.com/mixvlad/TarotCards/"
    f"{RWS_ART_REVISION}/tarot/rider-waite/720px"
)

_RWS_BY_CODE = {card.code: card for card in RWS_78_V1.cards}
_SUIT_FILENAMES = {
    "wands": "Wands",
    "cups": "Cups",
    "swords": "Swords",
    "pentacles": "Pents",
}
_RANK_FILENAMES = {
    "ace": "01",
    "02": "02",
    "03": "03",
    "04": "04",
    "05": "05",
    "06": "06",
    "07": "07",
    "08": "08",
    "09": "09",
    "10": "10",
    "page": "11",
    "knight": "12",
    "queen": "13",
    "king": "14",
}


def _minor_remote_url(symbol_id: str) -> str | None:
    card = _RWS_BY_CODE.get(symbol_id)
    if card is None or card.arcana is not TarotArcana.MINOR:
        return None
    if card.suit is None or card.rank is None:
        return None
    suit = _SUIT_FILENAMES.get(card.suit.value)
    rank = _RANK_FILENAMES.get(card.rank)
    if suit is None or rank is None:
        return None
    return f"{RWS_ART_BASE_URL}/{suit}{rank}.jpg"


@cache
def card_art(symbol_id: str) -> Art | None:
    """Return exact card art for a known RWS symbol, never a generic substitute."""

    card = _RWS_BY_CODE.get(symbol_id)
    if card is None:
        return None

    path = TAROT_ASSET_DIR / f"{symbol_id}.jpg"
    if path.is_file():
        return Art(key=f"tarot:{symbol_id}", path=path)

    remote_url = _minor_remote_url(symbol_id)
    if remote_url is None:
        return None
    return Art(key=f"tarot:{symbol_id}", path=remote_url)


def deck_is_installed() -> bool:
    """Whether the bespoke local Major Arcana layer is present for visual continuity."""

    return TAROT_ASSET_DIR.is_dir() and any(TAROT_ASSET_DIR.glob("major_*.jpg"))
