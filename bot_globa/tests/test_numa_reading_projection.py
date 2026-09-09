"""Typed Reading-to-funnel projection tests without DB, Telegram or LLM calls."""

from uuid import uuid4

from app.providers.analytics import OracleProductEvent
from app.providers.numa_product_analytics import ProductFunnelEvent
from app.providers.numa_reading_projection import project_personal_reading_event


def _reading_properties(persona_code: str = "tarot_reader") -> dict[str, str]:
    return {
        "event_version": "oracle-product-events-v1",
        "reading_id": str(uuid4()),
        "persona_code": persona_code,
        "topic_code": "decision",
    }


def test_started_reading_becomes_question_accepted() -> None:
    properties = _reading_properties()

    projected = project_personal_reading_event(
        OracleProductEvent.READING_STARTED.value,
        properties,
    )

    assert projected is not None
    event, payload = projected
    assert event == ProductFunnelEvent.QUESTION_ACCEPTED.value
    assert payload["entity_id"] == properties["reading_id"]
    assert payload["flow"] == "personal"
    assert payload["source"] == "normal_start"


def test_preview_ready_preserves_latest_safe_entry_attribution() -> None:
    properties = _reading_properties("love_oracle")
    entry = {
        "flow": "personal",
        "source": "daily_horoscope",
        "scenario_version": "personal_day_forecast_v1",
        "experiment_assignment": "variant_b",
        "conversion_hook": "conversion_hook_v1",
        "test_traffic": "false",
        "calculation_timezone": "Europe/Moscow",
    }

    projected = project_personal_reading_event(
        OracleProductEvent.READING_PREVIEW_READY.value,
        properties,
        entry,
    )

    assert projected is not None
    event, payload = projected
    assert event == ProductFunnelEvent.FREE_ANSWER_READY.value
    assert payload["source"] == "daily_horoscope"
    assert payload["scenario_version"] == "personal_day_forecast_v1"
    assert payload["experiment_assignment"] == "variant_b"
    assert payload["calculation_timezone"] == "Europe/Moscow"


def test_group_entry_cannot_override_personal_reading_attribution() -> None:
    properties = _reading_properties()
    group_entry = {
        "flow": "group",
        "source": "group_duel",
        "scenario_version": "group_duel_v1",
    }

    projected = project_personal_reading_event(
        OracleProductEvent.READING_STARTED.value,
        properties,
        group_entry,
    )

    assert projected is not None
    _, payload = projected
    assert payload["flow"] == "personal"
    assert payload["source"] == "normal_start"


def test_astrology_is_not_mislabeled_as_personal_tarot_funnel() -> None:
    properties = _reading_properties("astrologer")

    assert (
        project_personal_reading_event(
            OracleProductEvent.READING_STARTED.value,
            properties,
        )
        is None
    )


def test_unrelated_oracle_event_is_not_projected() -> None:
    properties = _reading_properties()

    assert (
        project_personal_reading_event(
            OracleProductEvent.READING_FEEDBACK_SUBMITTED.value,
            properties,
        )
        is None
    )
