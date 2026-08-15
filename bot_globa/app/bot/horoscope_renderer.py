"""Deterministic Horoscope renderer using application facts for every chart label."""

from dataclasses import dataclass

from app.bot.reading_renderer import chunk_text
from app.bot.typography import quote
from app.domain.horoscope import (
    HOROSCOPE_RENDERER_VERSION,
    AstrologyReadingResult,
    HoroscopeFact,
    HoroscopeFactBundle,
    HoroscopeFactKind,
    HoroscopeLimitation,
)

PREVIEW_INTERPRETATIONS = 2

_BODY_LABELS = {
    "sun": "Солнце",
    "moon": "Луна",
    "mercury": "Меркурий",
    "venus": "Венера",
    "mars": "Марс",
    "jupiter": "Юпитер",
    "saturn": "Сатурн",
    "uranus": "Уран",
    "neptune": "Нептун",
    "pluto": "Плутон",
}
_SIGN_LABELS = {
    "aries": "Овен",
    "taurus": "Телец",
    "gemini": "Близнецы",
    "cancer": "Рак",
    "leo": "Лев",
    "virgo": "Дева",
    "libra": "Весы",
    "scorpio": "Скорпион",
    "sagittarius": "Стрелец",
    "capricorn": "Козерог",
    "aquarius": "Водолей",
    "pisces": "Рыбы",
}
_ASPECT_LABELS = {
    "conjunction": "соединение",
    "sextile": "секстиль",
    "square": "квадрат",
    "trine": "трин",
    "opposition": "оппозиция",
}
_LIMITATION_LABELS = {
    HoroscopeLimitation.ENTERTAINMENT_ONLY: (
        "Интерпретация предназначена для развлечения и саморефлексии."
    ),
    HoroscopeLimitation.BIRTH_TIME_UNKNOWN: (
        "Время рождения неизвестно: дома и асцендент не рассчитывались."
    ),
    HoroscopeLimitation.SAMPLED_TRANSITS: (
        "Прогноз использует расчётные снимки начала, середины и конца периода."
    ),
    HoroscopeLimitation.NO_CERTAIN_PREDICTION: (
        "Астрологический текст описывает возможные темы, а не гарантированные события."
    ),
}
_GENERIC_LIMITATIONS = frozenset(
    {
        HoroscopeLimitation.ENTERTAINMENT_ONLY,
        HoroscopeLimitation.NO_CERTAIN_PREDICTION,
    }
)


class HoroscopeRenderError(ValueError):
    """Safe renderer error without generated or birth-profile content."""


@dataclass(frozen=True, slots=True)
class RenderedHoroscope:
    text: str
    facts_digest: str
    renderer_version: str = HOROSCOPE_RENDERER_VERSION

    def chunks(self) -> tuple[str, ...]:
        """Split into Telegram-sized messages without breaking a paragraph."""
        return chunk_text(self.text)


class HoroscopeRenderer:
    """Combine model interpretation with exact labels derived only from calculated facts."""

    def render(
        self,
        result: AstrologyReadingResult,
        facts: HoroscopeFactBundle,
    ) -> RenderedHoroscope:
        labels = self._verified_labels(result, facts)
        lines = [f"<b>{quote(result.title)}</b>", "", quote(result.overview)]
        lines.extend(("", "<b>Расчётные опоры:</b>"))
        lines.extend(self._interpretation_lines(result, labels))
        lines.extend(("", "<b>Темы:</b>"))
        lines.extend(f"• {quote(theme)}" for theme in result.themes)
        lines.extend(("", "<b>Возможные сценарии:</b>"))
        for scenario in result.possible_scenarios:
            lines.append(f"• {quote(scenario.scenario)}")
            lines.extend(f"  — {quote(condition)}" for condition in scenario.conditions)
        if result.reflection_questions:
            lines.extend(("", "<b>Вопросы для размышления:</b>"))
            lines.extend(f"• {quote(question)}" for question in result.reflection_questions)
        lines.extend(("", f"<b>Практический шаг:</b> {quote(result.practical_step)}"))
        lines.extend(self._closing_lines(result))
        lines.extend(
            (
                "",
                "Разбор сохранён в «Моих разборах». Хотите уточнить один момент? "
                "Этот вопрос уже включён в покупку.",
            )
        )
        return RenderedHoroscope(
            text="\n".join(lines),
            facts_digest=result.facts_digest,
        )

    def render_preview(
        self,
        result: AstrologyReadingResult,
        facts: HoroscopeFactBundle,
    ) -> RenderedHoroscope:
        """Show the calculation is real and useful while withholding the paid depth."""
        labels = self._verified_labels(result, facts)
        lines = [f"<b>{quote(result.title)}</b>", "", quote(result.overview)]
        lines.extend(("", "<b>Расчётные опоры:</b>"))
        lines.extend(self._interpretation_lines(result, labels, limit=PREVIEW_INTERPRETATIONS))
        if result.themes:
            lines.extend(("", "<b>Темы:</b>"))
            lines.extend(f"• {quote(theme)}" for theme in result.themes)
        lines.extend(("", f"<b>Практический шаг:</b> {quote(result.practical_step)}"))
        lines.extend(
            (
                "",
                "В полном разборе: возможные сценарии, дополнительные расчётные опоры "
                "и следующий шаг.",
            )
        )
        lines.extend(self._closing_lines(result))
        return RenderedHoroscope(
            text="\n".join(lines),
            facts_digest=result.facts_digest,
        )

    def render_micro_preview(
        self,
        result: AstrologyReadingResult,
        facts: HoroscopeFactBundle,
    ) -> RenderedHoroscope:
        """Show one calculated personal signal after the first free preview is used."""

        labels = self._verified_labels(result, facts)
        lines = ["<b>Разбор готов.</b>", "", f"<b>Главная тема</b> — {quote(result.overview)}"]
        interpretations = self._interpretation_lines(result, labels, limit=1)
        if interpretations:
            lines.extend(("", "<b>Одна расчётная опора:</b>", *interpretations))
        lines.extend(
            (
                "",
                "Полная версия покажет возможные сценарии и практический следующий шаг.",
            )
        )
        lines.extend(self._closing_lines(result))
        return RenderedHoroscope(
            text="\n".join(lines),
            facts_digest=result.facts_digest,
        )

    def _verified_labels(
        self,
        result: AstrologyReadingResult,
        facts: HoroscopeFactBundle,
    ) -> dict[str, str]:
        if result.scope is not facts.scope:
            raise HoroscopeRenderError("Horoscope scope mismatch")
        if result.facts_digest != facts.digest():
            raise HoroscopeRenderError("Horoscope fact digest mismatch")
        return {fact.fact_id: self._label(fact) for fact in facts.facts}

    @staticmethod
    def _interpretation_lines(
        result: AstrologyReadingResult,
        labels: dict[str, str],
        *,
        limit: int | None = None,
    ) -> list[str]:
        selected = result.interpretations if limit is None else result.interpretations[:limit]
        lines: list[str] = []
        for interpretation in selected:
            try:
                references = "; ".join(labels[fact_id] for fact_id in interpretation.fact_ids)
            except KeyError as exc:
                raise HoroscopeRenderError("Horoscope references an unknown fact") from exc
            lines.append(f"• <b>{quote(references)}</b>\n  {quote(interpretation.text)}")
        return lines

    @staticmethod
    def _closing_lines(result: AstrologyReadingResult) -> list[str]:
        technical = [value for value in result.limitations if value not in _GENERIC_LIMITATIONS]
        lines: list[str] = []
        if technical:
            lines.extend(("", "<b>Ограничения расчёта:</b>"))
            lines.extend(f"• {_LIMITATION_LABELS[value]}" for value in technical)
        return lines

    @staticmethod
    def share_text(result: AstrologyReadingResult) -> str:
        """Render the prevalidated privacy-safe share card without chart coordinates."""

        return f"{result.share_card.headline}\n{result.share_card.short_text}"

    def _label(self, fact: HoroscopeFact) -> str:
        details = fact.details
        if fact.kind in {HoroscopeFactKind.NATAL_PLANET, HoroscopeFactKind.TRANSIT_PLANET}:
            body = self._required_label(_BODY_LABELS, details, "body")
            sign = self._required_label(_SIGN_LABELS, details, "sign")
            degree = self._degree(details, "sign_degree_millidegrees")
            retrograde = " R" if details.get("retrograde") is True else ""
            if fact.kind is HoroscopeFactKind.TRANSIT_PLANET:
                sample_date = self._required_text(details, "sample_date")
                return f"{sample_date}: транзитный {body} — {sign} {degree}{retrograde}"
            return f"{body} — {sign} {degree}{retrograde}"
        if fact.kind is HoroscopeFactKind.NATAL_ASPECT:
            first = self._required_label(_BODY_LABELS, details, "first_body")
            second = self._required_label(_BODY_LABELS, details, "second_body")
            aspect = self._required_label(_ASPECT_LABELS, details, "kind")
            orb = self._degree(details, "orb_millidegrees")
            return f"{first} — {aspect} — {second}, орб {orb}"
        if fact.kind is HoroscopeFactKind.NATAL_HOUSE:
            number = details.get("number")
            if not isinstance(number, int):
                raise HoroscopeRenderError("Invalid Horoscope house fact")
            sign = self._required_label(_SIGN_LABELS, details, "sign")
            degree = self._degree(details, "cusp_longitude_millidegrees", modulo=30_000)
            return f"Дом {number} — {sign} {degree}"
        if fact.kind is HoroscopeFactKind.NATAL_ASCENDANT:
            sign = self._required_label(_SIGN_LABELS, details, "sign")
            degree = self._degree(details, "sign_degree_millidegrees")
            return f"Асцендент — {sign} {degree}"
        if fact.kind is HoroscopeFactKind.TRANSIT_NATAL_ASPECT:
            sample_date = self._required_text(details, "sample_date")
            transit = self._required_label(_BODY_LABELS, details, "transit_body")
            natal = self._required_label(_BODY_LABELS, details, "natal_body")
            aspect = self._required_label(_ASPECT_LABELS, details, "kind")
            orb = self._degree(details, "orb_millidegrees")
            return f"{sample_date}: транзитный {transit} — {aspect} — натальный {natal}, орб {orb}"
        raise HoroscopeRenderError("Unsupported Horoscope fact kind")

    @staticmethod
    def _required_text(details: dict[str, object], key: str) -> str:
        value = details.get(key)
        if not isinstance(value, str) or not value:
            raise HoroscopeRenderError("Invalid Horoscope fact text")
        return value

    @classmethod
    def _required_label(
        cls,
        labels: dict[str, str],
        details: dict[str, object],
        key: str,
    ) -> str:
        value = cls._required_text(details, key)
        try:
            return labels[value]
        except KeyError as exc:
            raise HoroscopeRenderError("Unsupported Horoscope fact label") from exc

    @staticmethod
    def _degree(
        details: dict[str, object],
        key: str,
        *,
        modulo: int | None = None,
    ) -> str:
        value = details.get(key)
        if not isinstance(value, int):
            raise HoroscopeRenderError("Invalid Horoscope degree fact")
        if modulo is not None:
            value %= modulo
        return f"{value / 1000:.3f}°"
