from datetime import date

from app.bot.personal_oracle_handlers import (
    needs_route_clarification,
    route_from_clarification,
)
from app.bot.persona_flows import TAROT_FLOW
from app.domain.natal_chart import ZodiacSign
from app.domain.persona import persona_definition
from app.prompts.horoscope import load_horoscope_prompts
from app.prompts.oracle import load_oracle_reading_prompts
from app.prompts.reading import load_reading_prompts
from app.services.daily_horoscope_editorial import build_editorial_daily_horoscope
from app.services.daily_horoscope_generation import (
    DailyEditorialResult,
    DailyEditorialSign,
    DailyHoroscopeGenerationService,
)


class _UnusedLLM:
    async def generate_structured(self, request):  # pragma: no cover - not called in these tests
        raise AssertionError(request)


def test_daily_guard_catches_same_sign_temporal_repeat() -> None:
    previous = build_editorial_daily_horoscope(date(2026, 10, 10))
    result = DailyEditorialResult(
        theme=previous.theme if len(previous.theme) >= 18 else previous.theme + " сегодня",
        signs=[
            DailyEditorialSign(
                sign=item.sign,
                text=(item.text if len(item.text) >= 35 else item.text + " Проверьте следующий шаг."),
            )
            for item in previous.signs
        ],
    )
    service = DailyHoroscopeGenerationService(_UnusedLLM())

    issues = service.repetition_issues(result, (previous,))

    assert any(issue.field.startswith("sign:") for issue in issues)


def test_auto_route_asks_when_intent_is_genuinely_low_signal() -> None:
    assert needs_route_clarification("Я не понимаю, что сейчас вообще происходит") is True
    assert needs_route_clarification("Стоит ли менять работу в этом месяце?") is False
    assert needs_route_clarification("Сделай расклад на ближайшее будущее") is False


def test_route_clarification_can_explicitly_choose_tarot() -> None:
    choice = route_from_clarification("Я не понимаю, что происходит", "tarot")

    assert choice is not None
    assert choice.flow is TAROT_FLOW
    assert choice.topic == "general_forecast"


def test_new_personal_readings_use_editorial_prompt_versions() -> None:
    assert persona_definition("tarot_reader").prompt_version == "tarot-reader-v5"  # type: ignore[union-attr]
    assert persona_definition("love_oracle").prompt_version == "love-oracle-v3"  # type: ignore[union-attr]
    assert (
        persona_definition("mystical_psychologist").prompt_version  # type: ignore[union-attr]
        == "mystical-psychologist-v3"
    )
    assert persona_definition("astrologer").prompt_version == "astrologer-v3"  # type: ignore[union-attr]


def test_old_and_new_prompt_versions_remain_loadable() -> None:
    assert load_oracle_reading_prompts("tarot-reader-v4")
    assert load_oracle_reading_prompts("tarot-reader-v5")
    assert load_oracle_reading_prompts("mystical-psychologist-v2")
    assert load_oracle_reading_prompts("mystical-psychologist-v3")
    assert load_reading_prompts("love-oracle-v2")
    assert load_reading_prompts("love-oracle-v3")
    assert load_horoscope_prompts("astrologer-v2")
    assert load_horoscope_prompts("astrologer-v3")


def test_zodiac_enum_still_has_all_twelve_daily_targets() -> None:
    assert len(tuple(ZodiacSign)) == 12
