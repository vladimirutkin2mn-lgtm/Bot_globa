"""Render the paid full tarot result without exposing private source text."""

# ruff: noqa: RUF001

from dataclasses import dataclass

from app.bot.tarot_renderer import TARGET_CHUNK, TELEGRAM_LIMIT
from app.domain.reading import SymbolOrientation
from app.services.tarot_reading import TarotPreviewOutcome


@dataclass(frozen=True, slots=True)
class RenderedTarotFull:
    chunks: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.chunks or any(
            not chunk or len(chunk) > TELEGRAM_LIMIT for chunk in self.chunks
        ):
            raise ValueError("invalid full tarot chunks")


class TarotFullRenderer:
    """Reveal all validated interpretation sections after paid entitlement."""

    def render(self, outcome: TarotPreviewOutcome) -> RenderedTarotFull:
        result = outcome.generation.result
        if result is None:
            raise ValueError("full tarot render requires a completed structured result")
        cards_by_position = {card.position: card for card in outcome.cards}
        symbol_sections: list[str] = []
        for index, symbol in enumerate(result.symbols, start=1):
            selected = cards_by_position.get(symbol.position)
            card_name = selected.card.name_ru if selected is not None else symbol.symbol_id
            orientation = self._orientation(symbol.orientation)
            symbol_sections.append(f"{index}. {card_name} — {orientation}\n{symbol.interpretation}")

        pattern_lines = [f"• {value}" for value in result.patterns]
        scenario_sections = []
        for index, scenario in enumerate(result.possible_scenarios, start=1):
            conditions = "\n".join(f"  • {value}" for value in scenario.conditions)
            scenario_sections.append(
                f"Сценарий {index}: {scenario.scenario}\nУсловия:\n{conditions}"
            )
        question_lines = [f"• {value}" for value in result.reflection_questions]

        sections = [
            f"🔮 Полный расклад: {result.title}",
            result.opening,
            "Карты и позиции:\n\n" + "\n\n".join(symbol_sections),
        ]
        if pattern_lines:
            sections.append("Паттерны:\n" + "\n".join(pattern_lines))
        sections.append("Возможные сценарии:\n\n" + "\n\n".join(scenario_sections))
        if question_lines:
            sections.append("Вопросы для рефлексии:\n" + "\n".join(question_lines))
        sections.extend(
            [
                f"Практический шаг:\n{result.practical_step}",
                f"Границы интерпретации:\n{result.uncertainty_note}",
                (
                    "Это развлекательная практика для рефлексии, а не достоверное "
                    "предсказание или профессиональная консультация."
                ),
            ]
        )
        return RenderedTarotFull(self._chunks(tuple(sections)))

    @staticmethod
    def _orientation(orientation: SymbolOrientation) -> str:
        return "перевёрнутая" if orientation is SymbolOrientation.REVERSED else "прямая"

    @staticmethod
    def _chunks(sections: tuple[str, ...]) -> tuple[str, ...]:
        chunks: list[str] = []
        current = ""
        for section in sections:
            if len(section) > TELEGRAM_LIMIT:
                raise ValueError("full tarot section exceeds Telegram limit")
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
