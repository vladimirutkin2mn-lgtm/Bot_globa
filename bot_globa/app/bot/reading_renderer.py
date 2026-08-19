"""Render a validated structured reading into bounded Telegram messages.

Persona-neutral behavior, persona-specific wording. Nothing here reads the private source
text — only the already validated result and copy configured for the selected persona.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from app.bot.conversion_hooks import (
    DEFAULT_READING_HOOK,
    ConversionHookCopy,
    render_grounded_hook,
)
from app.bot.typography import quote
from app.domain.conversion_experiment import ConversionHookVariant
from app.domain.reading import SymbolOrientation
from app.domain.reading_generation import ReadingSymbolContext
from app.domain.reading_result import ReadingResult
from app.services.persona_reading import PersonaPreviewOutcome

TELEGRAM_LIMIT = 4096
TARGET_CHUNK = 3600

REVEAL_TITLE = "Расклад складывается"
REVEAL_CLOSING = "Читаю расклад…"


@dataclass(frozen=True, slots=True)
class ReadingCopy:
    """Persona wording for rendered preview and full-reading views."""

    emoji: str
    full_title_prefix: str
    drawn_symbols_title: str
    result_symbols_title: str
    main_theme_title: str = "Главная тема"
    practical_step_title: str = "Практический шаг"
    uncertainty_title: str = "Важно"
    patterns_title: str = "Паттерны"
    scenarios_title: str = "Возможные сценарии"
    reflection_title: str = "Вопросы для рефлексии"
    hook: ConversionHookCopy = DEFAULT_READING_HOOK
    hook_by_symbol_set: tuple[tuple[str, ConversionHookCopy], ...] = ()


def render_preview(outcome: PersonaPreviewOutcome, copy: ReadingCopy) -> tuple[str, ...]:
    """Give the diagnosis for free and reserve scenarios/conditions/action for the unlock."""
    result = _completed_result(outcome)
    sections = [
        f"{copy.emoji} <b>Быстрый взгляд</b>",
        f"<b>{quote(result.title)}</b>",
    ]
    if outcome.symbols:
        drawn = "\n".join(
            f"{index}. <b>{quote(context.display_name)}</b> — "
            f"{orientation_label(context.symbol.orientation)}"
            for index, context in enumerate(outcome.symbols, start=1)
        )
        sections.append(f"<b>{copy.drawn_symbols_title}</b>\n{drawn}")
    pattern = result.patterns[0] if result.patterns else result.opening
    sections.extend(
        [
            f"<b>{copy.main_theme_title}:</b> {quote(pattern)}\n\n{quote(result.opening)}",
            _locked_hook(
                result,
                copy,
                outcome.symbol_set_code,
                outcome.conversion_variant,
            ),
            (
                "<i>Это короткий слой разбора. Глубокий разбор покажет связи, условия "
                "сценариев и следующий шаг — без нового вопроса с нуля.</i>"
            ),
        ]
    )
    return chunk_sections(tuple(sections))


def render_micro_preview(outcome: PersonaPreviewOutcome, copy: ReadingCopy) -> tuple[str, ...]:
    """Give later readings one personal signal plus a grounded reason to unlock."""

    result = _completed_result(outcome)
    insight = result.patterns[0] if result.patterns else result.opening
    sections = [f"{copy.emoji} <b>Быстрый взгляд</b>"]
    if outcome.symbols:
        drawn = ", ".join(quote(context.display_name) for context in outcome.symbols)
        sections.append(f"<b>Зафиксированные карты:</b> {drawn}")
    sections.extend(
        (
            f"<b>{copy.main_theme_title}</b> — {quote(insight)}",
            _locked_hook(
                result,
                copy,
                outcome.symbol_set_code,
                outcome.conversion_variant,
            ),
            "<i>Глубокий разбор продолжит именно эту историю и этот расклад.</i>",
        )
    )
    return chunk_sections(tuple(sections))


def render_full(outcome: PersonaPreviewOutcome, copy: ReadingCopy) -> tuple[str, ...]:
    """Reveal every validated interpretation section after a paid entitlement."""
    result = _completed_result(outcome)
    sections = [
        f"{copy.emoji} <b>Глубокий разбор · {copy.full_title_prefix}: {quote(result.title)}</b>",
        quote(result.opening),
    ]

    names = {context.symbol.position: context.display_name for context in outcome.symbols}
    symbol_sections = [
        f"{index}. <b>{quote(names.get(symbol.position, symbol.symbol_id))}</b> — "
        f"{orientation_label(symbol.orientation)}\n{quote(symbol.interpretation)}"
        for index, symbol in enumerate(result.symbols, start=1)
    ]
    if symbol_sections:
        sections.append(f"<b>{copy.result_symbols_title}</b>\n\n" + "\n\n".join(symbol_sections))
    if result.patterns:
        sections.append(
            f"<b>{copy.patterns_title}:</b>\n"
            + "\n".join(f"• {quote(value)}" for value in result.patterns)
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
        sections.append(f"<b>{copy.scenarios_title}:</b>\n\n" + "\n\n".join(scenarios))
    if result.reflection_questions:
        sections.append(
            f"<b>{copy.reflection_title}:</b>\n"
            + "\n".join(f"• {quote(value)}" for value in result.reflection_questions)
        )
    sections.extend(
        [
            f"<b>{copy.practical_step_title}:</b>\n{quote(result.practical_step)}",
            (
                "Разбор сохранён в «Моих историях». В течение этого сеанса можно задать "
                "уточняющий вопрос — Numa продолжит с уже известным контекстом."
            ),
        ]
    )
    return chunk_sections(tuple(sections))


def reveal_progress(revealed: int, total: int) -> str:
    if not 0 <= revealed <= total:
        raise ValueError("revealed symbols are outside the spread")
    return "▰" * revealed + "▱" * (total - revealed)


def render_reveal(
    copy: ReadingCopy,
    symbols: Sequence[ReadingSymbolContext],
    revealed: int,
) -> str:
    if not 0 < revealed <= len(symbols):
        raise ValueError("revealed symbols are outside the spread")
    drawn = "\n".join(
        f"{index}. <b>{quote(context.display_name)}</b> — "
        f"{orientation_label(context.symbol.orientation)}"
        for index, context in enumerate(symbols[:revealed], start=1)
    )
    return (
        f"{copy.emoji} <b>{REVEAL_TITLE}</b>\n"
        f"{reveal_progress(revealed, len(symbols))}\n\n"
        f"{drawn}\n\n"
        f"<i>{REVEAL_CLOSING}</i>"
    )


def _locked_hook(
    result: ReadingResult,
    copy: ReadingCopy,
    symbol_set_code: str | None,
    variant: ConversionHookVariant,
) -> str:
    hook = copy.hook
    if symbol_set_code is not None:
        hook = next(
            (candidate for code, candidate in copy.hook_by_symbol_set if code == symbol_set_code),
            hook,
        )
    return render_grounded_hook(result.possible_scenarios, hook, variant)


def chunk_text(text: str) -> tuple[str, ...]:
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


def orientation_label(orientation: SymbolOrientation) -> str:
    return "перевёрнутая" if orientation is SymbolOrientation.REVERSED else "прямая"