"""Deterministic symbolic selection independent from the LLM provider."""

import hashlib
from dataclasses import dataclass
from uuid import UUID

from app.domain.reading import ReadingSymbolInput, SymbolOrientation
from app.domain.tarot import MAJOR_ARCANA_V1, TarotCard, TarotCatalog, TarotSpread, tarot_spread


class UnknownSpreadError(LookupError):
    """The requested spread is not defined by the current engine version."""


@dataclass(frozen=True, slots=True)
class SelectedTarotCard:
    ordinal: int
    card: TarotCard
    position: str
    orientation: SymbolOrientation
    catalog_version: str

    @property
    def interpretation_theme(self) -> str:
        if self.orientation is SymbolOrientation.REVERSED:
            return self.card.reversed_theme
        return self.card.upright_theme

    def to_reading_symbol(self) -> ReadingSymbolInput:
        return ReadingSymbolInput(
            symbol_id=self.card.code,
            position=self.position,
            orientation=self.orientation,
            catalog_version=self.catalog_version,
        )


class TarotSymbolicEngine:
    """Select unique cards deterministically from a reading-scoped seed."""

    version = "tarot-symbolic-v1"

    def __init__(self, catalog: TarotCatalog = MAJOR_ARCANA_V1) -> None:
        self._catalog = catalog

    def draw(self, reading_id: UUID, spread_code: str) -> tuple[SelectedTarotCard, ...]:
        spread = tarot_spread(spread_code)
        if spread is None:
            raise UnknownSpreadError(f"unknown tarot spread: {spread_code}")
        if len(spread.positions) > len(self._catalog.cards):
            raise ValueError("tarot spread is larger than the configured catalog")
        seed = self._seed(reading_id, spread)
        ordered_cards = sorted(
            self._catalog.cards,
            key=lambda card: self._digest(seed, "card", card.code),
        )
        return tuple(
            SelectedTarotCard(
                ordinal=index,
                card=card,
                position=position,
                orientation=self._orientation(seed, spread, card),
                catalog_version=self._catalog.version,
            )
            for index, (position, card) in enumerate(
                zip(spread.positions, ordered_cards, strict=True)
            )
        )

    def _seed(self, reading_id: UUID, spread: TarotSpread) -> bytes:
        value = f"{self.version}:{self._catalog.version}:{spread.code}:{reading_id}"
        return hashlib.sha256(value.encode()).digest()

    @staticmethod
    def _digest(seed: bytes, namespace: str, value: str) -> bytes:
        return hashlib.sha256(seed + b":" + namespace.encode() + b":" + value.encode()).digest()

    def _orientation(
        self,
        seed: bytes,
        spread: TarotSpread,
        card: TarotCard,
    ) -> SymbolOrientation:
        if not spread.allow_reversed:
            return SymbolOrientation.UPRIGHT
        digest = self._digest(seed, "orientation", card.code)
        return SymbolOrientation.REVERSED if digest[0] & 1 else SymbolOrientation.UPRIGHT
