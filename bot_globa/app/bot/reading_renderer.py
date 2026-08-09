"""Render a validated structured reading into bounded Telegram messages.

Persona-neutral: the only thing that varies is the wording supplied by `ReadingCopy`.
Nothing here reads the private source text — only the already validated result.
"""

from dataclasses import dataclass

from app.domain.reading import SymbolOrientation
from app.domain.reading_result import ReadingResult
from app.services.persona_reading import PersonaPreviewOutcome

TELEGRAM_LIMIT = 4096
TARGET_CHUNK = 3600

DISCLAIMER = (
    "Это развлекательная практика для рефлексии, а не достоверное предсказание "
    "или профессиональная консультация."
)


@dataclass(frozen=True, slots=True)
class ReadingCopy:
    """Persona wording for the two rendered views."""

    emoji: str
    full_title_prefix: str
    drawn_symbols_title: str
    result_symbols_title: str


def render_preview(outcome: PersonaPreviewOutcome, copy: ReadingCopy) -> tuple[str, ...]:
    """Show enough value to be worth reading without claiming factual prediction."""
    result = _completed_result(outcome)
    sections = [f"{copy.emoji} {result.title}"]
    if outcome.symbols:
        drawn = "\n".join(
            f"{index}. {context.display_name} — {_orientation(context.symbol.orientation)}"
            for index, context in enumerate(outcome.symbols, start=1)
        )
        sections.append(f"{copy.drawn_symbols_title}\n{drawn}")
    pattern = result.patterns[0] if result.patterns else "Явный общий паттерн не выделен."
    sections.extend(
        [
            result.opening,
            f"Главный паттерн:\n{pattern}",
            f"Практический шаг:\n{result.practical_step}",
            f"Важно:\n{result.uncertainty_note}",
            DISCLAIMER,
        ]
    )
    return chunk_sections(tuple(sections))


def render_full(outcome: PersonaPreviewOutcome, copy: ReadingCopy) -> tuple[str, ...]:
    """Reveal every validated interpretation section after a paid entitlement."""
    result = _completed_result(outcome)
    sections = [f"{copy.emoji} {copy.full_title_prefix}: {result.title}", result.opening]

    names = {context.symbol.position: context.display_name for context in outcome.symbols}
    symbol_sections = [
        f"{index}. {names.get(symbol.position, symbol.symbol_id)} — "
        f"{_orientation(symbol.orientation)}\n{symbol.interpretation}"
        for index, symbol in enumerate(result.symbols, start=1)
    ]
    if symbol_sections:
        sections.append(f"{copy.result_symbols_title}\n\n" + "\n\n".join(symbol_sections))
    if result.patterns:
        sections.append("Паттерны:\n" + "\n".join(f"• {value}" for value in result.patterns))

    scenarios = [
        "Сценарий {index}: {scenario}\nУсловия:\n{conditions}".format(
            index=index,
            scenario=scenario.scenario,
            conditions="\n".join(f"  • {value}" for value in scenario.conditions),
        )
        for index, scenario in enumerate(result.possible_scenarios, start=1)
    ]
    if scenarios:
        sections.append("Возможные сценарии:\n\n" + "\n\n".join(scenarios))
    if result.reflection_questions:
        sections.append(
            "Вопросы для рефлексии:\n"
            + "\n".join(f"• {value}" for value in result.reflection_questions)
        )
    sections.extend(
        [
            f"Практический шаг:\n{result.practical_step}",
            f"Границы интерпретации:\n{result.uncertainty_note}",
            DISCLAIMER,
        ]
    )
    return chunk_sections(tuple(sections))


def chunk_text(text: str) -> tuple[str, ...]:
    """Chunk free-form rendered text, preferring paragraph then line boundaries."""
    sections: list[str] = []
    for paragraph in text.split("\n\n"):
        if len(paragraph) <= TARGET_CHUNK:
            sections.append(paragraph)
            continue
        current = ""
        for line in paragraph.split("\n"):
            candidate = line if not current else f"{current}\n{line}"
            if len(candidate) <= TARGET_CHUNK:
                current = candidate
                continue
            if current:
                sections.append(current)
            current = line[:TARGET_CHUNK]
        if current:
            sections.append(current)
    return chunk_sections(tuple(section for section in sections if section))


def chunk_sections(sections: tuple[str, ...]) -> tuple[str, ...]:
    """Pack whole sections into as few messages as the Telegram limit allows."""
    chunks: list[str] = []
    current = ""
    for section in sections:
        if len(section) > TELEGRAM_LIMIT:
            raise ValueError("reading section exceeds the Telegram limit")
        candidate = section if not current else f"{current}\n\n{section}"
        if len(candidate) <= TARGET_CHUNK:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = section
    if current:
        chunks.append(current)
    if not chunks:
        raise ValueError("reading render produced no chunks")
    return tuple(chunks)


def _completed_result(outcome: PersonaPreviewOutcome) -> ReadingResult:
    result = outcome.generation.result
    if result is None:
        raise ValueError("rendering requires a completed structured result")
    return result


def _orientation(orientation: SymbolOrientation) -> str:
    return "перевёрнутая" if orientation is SymbolOrientation.REVERSED else "прямая"
