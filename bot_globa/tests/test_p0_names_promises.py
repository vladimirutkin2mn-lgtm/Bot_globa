"""Contracts for P0-03 user-facing names and promises."""

from types import SimpleNamespace

from app.bot import texts
from app.bot.group_compatibility_handlers import _render_result
from app.bot.keyboards import onboarding_intro_keyboard
from app.bot.reading_followup_handlers import SESSION_EXPIRED
from app.domain.natal_chart import NatalBody, ZodiacSign
from app.domain.synastry import CompatibilityContext


def _callbacks() -> set[str]:
    keyboard = onboarding_intro_keyboard()
    return {
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data is not None
    }


def test_welcome_offers_useful_choices_without_intermediate_start() -> None:
    callbacks = _callbacks()

    assert "onboarding:intro" not in callbacks
    assert "oracle:auto" in callbacks
    assert "oracle:tarot" in callbacks
    assert "oracle:love" in callbacks
    assert "oracle:astro" in callbacks


def test_paid_reading_copy_matches_the_real_followup_entitlement() -> None:
    paywall = texts.PAYWALL.format(price="199 ₽")

    assert "до 3 уточняющих вопросов" in paywall
    assert "24 часов" in paywall
    assert "без доплаты" in paywall
    assert "«Моих историях»" in paywall


def test_followup_expiry_does_not_imply_the_purchased_result_disappears() -> None:
    assert "24 часа" in SESSION_EXPIRED
    assert "полный разбор остаётся доступен" in SESSION_EXPIRED
    assert "«Моих историях»" in SESSION_EXPIRED


def test_compatibility_percentages_are_described_as_playful_indicators() -> None:
    chart = SimpleNamespace(
        planets=[
            SimpleNamespace(body=NatalBody.SUN, sign=ZodiacSign.ARIES),
            SimpleNamespace(body=NatalBody.VENUS, sign=ZodiacSign.TAURUS),
            SimpleNamespace(body=NatalBody.MARS, sign=ZodiacSign.GEMINI),
        ],
        time_precision=None,
    )
    result = SimpleNamespace(
        context=CompatibilityContext.LOVE,
        overall=74,
        scores=SimpleNamespace(attraction=80, communication=70, emotional=69, stability=76),
        strongest="легко замечать сильные стороны друг друга",
        weakest="по-разному проживать напряжение",
        verdict="есть интересный ритм для разговора",
    )

    rendered = _render_result("А", "Б", chart, chart, result)  # type: ignore[arg-type]

    assert "Проценты здесь — игровые показатели совместимости" in rendered
    assert "не вероятность будущих событий" in rendered
