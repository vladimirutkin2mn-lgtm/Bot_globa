"""Render a validated structured reading into bounded Telegram messages.

Persona-neutral: the only thing that varies is the wording supplied by `ReadingCopy`.
Nothing here reads the private source text — only the already validated result.
"""

from dataclasses import dataclass

from app.bot.typography import quote
from app.domain.reading import SymbolOrientation
from app.domain.reading_result import ReadingResult
from app.services.persona_reading import PersonaPreviewOutcome

TELEGRAM_LIMIT = 4096
TARGET_CHUNK = 3600
# One line of the paid reading is enough to prove it continues; a spoiler is one tap from
# being read, so anything longer would simply be given away.
TEASER_LIMIT = 140

# Set apart from the reading rather than buried in it: the boundary between reflection
# and prediction is the product, so it is typographically distinct on every view.
DISCLAIMER = (
    "<i>Это развлекательная практика для рефлексии, а не достоверное предсказание "
    "или профессиональная консультация.</i>"
)


@dataclass(frozen=True, slots=True)
class ReadingCopy:
    """Persona wording for the two rendered views."""

    emoji: str
    full_title_prefix: str
    drawn_symbols_title: str
    result_symbols_title: str


def render_preview(outcome: PersonaPreviewOutcome, copy: ReadingCopy) -> tuple[str, ...]:
    """Show a meaningful first preview and an honest outline of the paid depth."""
    result = _completed_result(outcome)
    sections = [f"{copy.emoji} <b>{quote(result.title)}</b>"]
    if outcome.symbols:
        drawn = "\n".join(
            f"{index}. <b>{quote(context.display_name)}</b> — "
            f"{_orientation(context.symbol.orientation)}"
            for index, context in enumerate(outcome.symbols, start=1)
        )
        sections.append(f"<b>{copy.drawn_symbols_title}</b>\n{drawn}")
    pattern = result.patterns[0] if result.patterns else "Явный общий паттерн не выделен."
    sections.extend(
        [
            f"<b>Главная тема:</b> {quote(pattern)}\n\n{quote(result.opening)}",
            f"<b>Практический шаг:</b>\n{quote(result.practical_step)}",
            _locked_teaser(result),
            f"<b>Важно:</b>\n{quote(result.uncertainty_note)}",
            DISCLAIMER,
        ]
    )
    return chunk_sections(tuple(sections))


def render_micro_preview(outcome: PersonaPreviewOutcome, copy: ReadingCopy) -> tuple[str, ...]:
    """Give every later reading a short personal signal instead of a blind lock."""

    result = _completed_result(outcome)
    insight = result.patterns[0] if result.patterns else result.opening
    sections = [f"{copy.emoji} <b>Разбор готов</b>"]
    if outcome.symbols:
        drawn = ", ".join(quote(context.display_name) for context in outcome.symbols)
        sections.append(f"<b>Зафиксированные карты:</b> {drawn}")
    sections.extend(
        (
            f"<b>Главная тема</b> — {quote(insight)}",
            ("Полная версия покажет возможные сценарии и практический следующий шаг."),
            DISCLAIMER,
        )
    )
    return chunk_sections(tuple(sections))


def render_full(outcome: PersonaPreviewOutcome, copy: ReadingCopy) -> tuple[str, ...]:
    """Reveal every validated interpretation section after a paid entitlement."""
    result = _completed_result(outcome)
    sections = [
        f"{copy.emoji} <b>{copy.full_title_prefix}: {quote(result.title)}</b>",
        quote(result.opening),
    ]

    names = {context.symbol.position: context.display_name for context in outcome.symbols}
    symbol_sections = [
        f"{index}. <b>{quote(names.get(symbol.position, symbol.symbol_id))}</b> — "
        f"{_orientation(symbol.orientation)}\n{quote(symbol.interpretation)}"
        for index, symbol in enumerate(result.symbols, start=1)
    ]
    if symbol_sections:
        sections.append(f"<b>{copy.result_symbols_title}</b>\n\n" + "\n\n".join(symbol_sections))
    if result.patterns:
        sections.append(
            "<b>Паттерны:</b>\n" + "\n".join(f"• {quote(value)}" for value in result.patterns)
        )

    scenarios = [
        "<b>Сценарий {index}:</b> {scenario}\nУсловия:\n{conditions}".format(
            index=index,
            scenario=quote(scenario.scenario),
            conditions="\n".join(f"  • {quote(value)}" for value in scenario.conditions),
        )
        for index, scenario in enumerate(result.possible_scenarios, start=1)
    ]
    if scenarios:
        sections.append("<b>Возможные сценарии:</b>\n\n" + "\n\n".join(scenarios))
    if result.reflection_questions:
        sections.append(
            "<b>Вопросы для рефлексии:</b>\n"
            + "\n".join(f"• {quote(value)}" for value in result.reflection_questions)
        )
    sections.extend(
        [
            f"<b>Практический шаг:</b>\n{quote(result.practical_step)}",
            f"<b>Границы интерпретации:</b>\n{quote(result.uncertainty_note)}",
            DISCLAIMER,
            (
                "Разбор сохранён в «Моих разборах». Хотите уточнить один момент? "
                "Этот вопрос уже включён в покупку."
            ),
        ]
    )
    return chunk_sections(tuple(sections))


def _locked_teaser(result: ReadingResult) -> str:
    """Show that the paid depth exists by covering a real line of it, not by listing it.

    A promise ("two possible scenarios") is weaker than the thing itself under a blur, and
    an honest blur has to be real text rather than a placeholder. A Telegram spoiler is one
    tap away from being read, so only a single truncated line goes under it — enough to
    prove the reading continues, not enough to be the reading.
    """

    covered = (
        result.possible_scenarios[0].scenario
        if result.possible_scenarios
        else (result.reflection_questions[0] if result.reflection_questions else "")
    )
    lines = ["<b>В полном разборе:</b>"]
    if covered:
        lines.append(f"<tg-spoiler>{quote(_shortened(covered))}</tg-spoiler>")
    lines.extend(
        (
            "• почему это повторяется;",
            "• два возможных сценария и условия каждого;",
            "• что можно сделать в ближайшие 7 дней.",
        )
    )
    return "\n".join(lines)


def _shortened(value: str, maximum: int = TEASER_LIMIT) -> str:
    """Cut at a word boundary so the covered line reads as a sentence, not a fragment."""

    if len(value) <= maximum:
        return value
    head = value[:maximum].rsplit(" ", 1)[0].rstrip(" ,.;:—-")
    return f"{head}…"


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
