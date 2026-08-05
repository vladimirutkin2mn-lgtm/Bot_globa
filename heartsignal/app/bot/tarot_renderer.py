"""Render a bounded Telegram preview from an already validated tarot result."""

from dataclasses import dataclass

from app.domain.reading import SymbolOrientation
from app.services.tarot_reading import TarotPreviewOutcome

TELEGRAM_LIMIT = 4096
TARGET_CHUNK = 3600


@dataclass(frozen=True, slots=True)
class RenderedTarotPreview:
    chunks: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.chunks or any(
            not chunk or len(chunk) > TELEGRAM_LIMIT for chunk in self.chunks
        ):
            raise ValueError("invalid tarot preview chunks")


class TarotPreviewRenderer:
    """Expose enough value for a preview without claiming factual prediction."""

    def render(self, outcome: TarotPreviewOutcome) -> RenderedTarotPreview:
        result = outcome.generation.result
        if result is None:
            raise ValueError("tarot preview requires a completed structured result")
        card_lines = [
            f"{index}. {card.card.name_ru} — {self._orientation(card.orientation)}"
            for index, card in enumerate(outcome.cards, start=1)
        ]
        pattern = result.patterns[0] if result.patterns else "Явный общий паттерн не выделен."
        sections = (
            f"🔮 {result.title}",
            "Ваш расклад:\n" + "\n".join(card_lines),
            result.opening,
            f"Главный паттерн:\n{pattern}",
            f"Практический шаг:\n{result.practical_step}",
            f"Важно:\n{result.uncertainty_note}",
            (
                "Это развлекательная практика для рефлексии, а не достоверное предсказание "
                "или профессиональная консультация."
            ),
        )
        return RenderedTarotPreview(self._chunks(sections))

    @staticmethod
    def _orientation(orientation: SymbolOrientation) -> str:
        return "перевёрнутая" if orientation is SymbolOrientation.REVERSED else "прямая"

    @staticmethod
    def _chunks(sections: tuple[str, ...]) -> tuple[str, ...]:
        chunks: list[str] = []
        current = ""
        for section in sections:
            if len(section) > TELEGRAM_LIMIT:
                raise ValueError("tarot preview section exceeds Telegram limit")
            candidate = section if not current else f"{current}\n\n{section}"
            if len(candidate) <= TARGET_CHUNK:
                current = candidate
                continue
            if current:
                chunks.append(current)
            current = section
        if current:
            chunks.append(current)
        return tuple(chunks)
