"""Paid-reading sharing must stay owner-gated, anonymous and attributable to Numa."""

from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

from app.bot.horoscope_flow import HOROSCOPE_FLOW
from app.bot.persona_flows import TAROT_FLOW
from app.bot.reading_share_handlers import (
    SHARE_ENTRY_PAYLOAD,
    SHARE_FORMAT,
    SHARE_RENDERER_VERSION,
    _owned_share_card,
    _share_card_from_payload,
    build_telegram_share_url,
    render_public_share,
)
from app.domain.horoscope import (
    AstrologyInterpretation,
    AstrologyReadingResult,
    HoroscopeLimitation,
    HoroscopeScope,
)
from app.domain.reading_result import (
    ReadingResult,
    ReadingSafetyAssessment,
    ReadingScenario,
    ShareCardPayload,
)


def _card() -> ShareCardPayload:
    return ShareCardPayload(
        headline="Иногда развилка важнее ответа",
        short_text="Ситуация меняется не от ожидания, а от одного ясного шага.",
    )


def _reading_payload() -> dict[str, object]:
    result = ReadingResult(
        title="Разбор",
        opening="В ситуации есть напряжение.",
        symbols=[],
        patterns=["Главный паттерн уже виден."],
        possible_scenarios=[
            ReadingScenario(
                scenario="Ситуация станет яснее.",
                conditions=["Появится прямой разговор."],
            )
        ],
        reflection_questions=[],
        practical_step="Сформулировать один прямой вопрос.",
        uncertainty_note="Это один из возможных взглядов.",
        share_card=_card(),
        safety=ReadingSafetyAssessment(high_risk_detected=False, categories=[]),
    )
    return result.model_dump(mode="json")


def _astrology_payload() -> dict[str, object]:
    result = AstrologyReadingResult(
        title="Прогноз на сегодня",
        scope=HoroscopeScope.DAY_FORECAST,
        facts_digest="a" * 64,
        overview="Сегодня полезно не торопить решение.",
        interpretations=[
            AstrologyInterpretation(
                fact_ids=["fact:one"],
                text="Фон дня усиливает внимательность к деталям.",
            )
        ],
        themes=["Спокойный темп."],
        possible_scenarios=[
            ReadingScenario(
                scenario="Решение станет яснее к вечеру.",
                conditions=["Оставить место для новой информации."],
            )
        ],
        reflection_questions=[],
        practical_step="Не принимать решение на автомате.",
        limitations=[
            HoroscopeLimitation.ENTERTAINMENT_ONLY,
            HoroscopeLimitation.NO_CERTAIN_PREDICTION,
        ],
        uncertainty_note="Астрология не определяет события с гарантией.",
        share_card=_card(),
        safety=ReadingSafetyAssessment(high_risk_detected=False, categories=[]),
    )
    return result.model_dump(mode="json")


def test_public_share_contains_only_dedicated_card_and_numa_brand() -> None:
    text = render_public_share(_card())

    assert "Иногда развилка важнее ответа" in text
    assert "одного ясного шага" in text
    assert text.endswith("— Numa")
    assert "user_question" not in text
    assert "reading_id" not in text


def test_telegram_share_url_uses_aggregate_referral_without_reading_id() -> None:
    reading_id = uuid4()
    url = build_telegram_share_url("@NumaTestBot", _card())
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "t.me"
    assert parsed.path == "/share/url"
    assert query["url"] == [f"https://t.me/NumaTestBot?start={SHARE_ENTRY_PAYLOAD}"]
    assert "— Numa" in query["text"][0]
    assert str(reading_id) not in url
    assert SHARE_FORMAT == "insight_card_v1"
    assert SHARE_RENDERER_VERSION == "personal_share_v1"


def test_both_personal_result_schemas_recover_the_same_share_contract() -> None:
    reading = _share_card_from_payload(_reading_payload())
    astrology = _share_card_from_payload(_astrology_payload())

    assert reading == _card()
    assert astrology == _card()


def test_full_result_keyboards_expose_one_share_action_with_safe_callback_size() -> None:
    reading_id = uuid4()

    for flow in (TAROT_FLOW, HOROSCOPE_FLOW):
        keyboard = flow.full_result_keyboard(reading_id)
        buttons = [button for row in keyboard.inline_keyboard for button in row]
        share = [button for button in buttons if button.text == "✨ Поделиться инсайтом"]
        assert len(share) == 1
        assert share[0].callback_data == f"rfs:preview:{reading_id}"
        assert len(share[0].callback_data or "") <= 64


class FakeHistory:
    def __init__(self, owned: bool) -> None:
        self.owned = owned

    async def owns_full(self, user_id: UUID, reading_id: UUID) -> bool:
        return self.owned


class FakeReadings:
    def __init__(self, payload: dict[str, object] | None) -> None:
        self.payload = payload
        self.loads = 0

    async def load_result(self, reading_id: UUID, user_id: UUID) -> dict[str, object] | None:
        self.loads += 1
        return self.payload


async def test_share_card_requires_owned_full_reading_before_decrypting_result() -> None:
    readings = FakeReadings(_reading_payload())

    denied = await _owned_share_card(
        uuid4(),
        uuid4(),
        FakeHistory(False),  # type: ignore[arg-type]
        readings,  # type: ignore[arg-type]
    )
    assert denied is None
    assert readings.loads == 0

    allowed = await _owned_share_card(
        uuid4(),
        uuid4(),
        FakeHistory(True),  # type: ignore[arg-type]
        readings,  # type: ignore[arg-type]
    )
    assert allowed == _card()
    assert readings.loads == 1
