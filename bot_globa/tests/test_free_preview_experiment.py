"""P2 free-preview experiment contracts without database, Telegram or LLM calls."""

from uuid import UUID, uuid4

from app.bot.numa_runtime_analytics import RuntimeProductSignal, runtime_attribution_for_user
from app.bot.persona_flows import TAROT_FLOW
from app.bot.reading_renderer import render_preview
from app.domain.conversion_experiment import (
    FREE_PREVIEW_EXPERIMENT,
    ConversionHookVariant,
    FreePreviewVariant,
    free_preview_experiment_assignment,
    free_preview_variant,
)
from app.domain.reading import SymbolOrientation
from app.domain.reading_result import ReadingResult
from app.providers.analytics import OracleProductEvent
from app.providers.numa_product_analytics import ProductFlow, ProductSource
from app.providers.numa_reading_projection import project_personal_reading_event
from app.services.numa_product_analytics import ProductAttribution
from app.services.persona_reading import PersonaPreviewOutcome
from app.services.reading_generation import ReadingGenerationResult, ReadingGenerationStatus
from tests.test_reading_result_validator import _valid_payload


def _reading() -> ReadingResult:
    payload = _valid_payload()
    symbols = payload["symbols"]
    assert isinstance(symbols, list)
    for symbol in symbols:
        assert isinstance(symbol, dict)
        orientation = symbol["orientation"]
        assert isinstance(orientation, str)
        symbol["orientation"] = SymbolOrientation(orientation)
    return ReadingResult.model_validate(payload)


def _outcome(
    result: ReadingResult,
    variant: FreePreviewVariant,
    *,
    hook_variant: ConversionHookVariant = ConversionHookVariant.A,
) -> PersonaPreviewOutcome:
    return PersonaPreviewOutcome(
        reading_id=uuid4(),
        generation=ReadingGenerationResult(
            status=ReadingGenerationStatus.COMPLETED,
            result=result,
        ),
        symbol_set_code="decision_five_v1",
        conversion_variant=hook_variant,
        free_preview_variant=variant,
    )


def test_free_preview_assignment_is_stable_and_has_both_arms() -> None:
    users = [UUID(int=value) for value in range(1, 65)]

    first = [free_preview_variant(user_id) for user_id in users]
    second = [free_preview_variant(user_id) for user_id in users]

    assert first == second
    assert set(first) == {FreePreviewVariant.BASELINE, FreePreviewVariant.COMPLETE}
    assert all(
        free_preview_experiment_assignment(user_id).startswith(f"{FREE_PREVIEW_EXPERIMENT}:")
        for user_id in users
    )


def test_runtime_assignment_does_not_replace_entry_source() -> None:
    user_id = uuid4()
    normal = RuntimeProductSignal(
        telegram_user_id=1,
        event_key="normal",
        attribution=ProductAttribution(
            flow=ProductFlow.PERSONAL,
            source=ProductSource.NORMAL_START,
            scenario_version="love_oracle_v1",
        ),
    )
    daily = RuntimeProductSignal(
        telegram_user_id=1,
        event_key="daily",
        attribution=ProductAttribution(
            flow=ProductFlow.PERSONAL,
            source=ProductSource.DAILY_HOROSCOPE,
            scenario_version="love_oracle_v1",
        ),
    )

    normal_attr = runtime_attribution_for_user(normal, user_id)
    daily_attr = runtime_attribution_for_user(daily, user_id)

    assert normal_attr.source is ProductSource.NORMAL_START
    assert daily_attr.source is ProductSource.DAILY_HOROSCOPE
    assert normal_attr.experiment_assignment == daily_attr.experiment_assignment
    assert normal_attr.experiment_assignment == free_preview_experiment_assignment(user_id)


def test_baseline_and_complete_preview_change_only_first_free_answer_content() -> None:
    result = _reading()
    baseline = "\n".join(
        render_preview(_outcome(result, FreePreviewVariant.BASELINE), TAROT_FLOW.copy)
    )
    complete = "\n".join(
        render_preview(_outcome(result, FreePreviewVariant.COMPLETE), TAROT_FLOW.copy)
    )

    assert result.possible_scenarios[0].scenario in baseline
    assert result.possible_scenarios[0].conditions[0] not in baseline
    assert result.practical_step not in baseline

    assert result.possible_scenarios[0].scenario not in complete
    assert result.practical_step in complete
    assert "В полном разборе" in complete


def test_baseline_preview_freezes_legacy_hook_arm_to_avoid_nested_text_test() -> None:
    result = _reading()
    rendered_b = render_preview(
        _outcome(
            result,
            FreePreviewVariant.BASELINE,
            hook_variant=ConversionHookVariant.B,
        ),
        TAROT_FLOW.copy,
    )
    rendered_c = render_preview(
        _outcome(
            result,
            FreePreviewVariant.BASELINE,
            hook_variant=ConversionHookVariant.C,
        ),
        TAROT_FLOW.copy,
    )

    assert rendered_b == rendered_c


def test_reading_projection_derives_arm_but_preserves_latest_entry_source() -> None:
    user_id = uuid4()
    reading_id = uuid4()
    properties = {
        "event_version": "oracle-product-events-v1",
        "reading_id": str(reading_id),
        "persona_code": "love_oracle",
        "topic_code": "love",
    }
    latest_entry = {
        "flow": "personal",
        "source": "daily_horoscope",
        "scenario_version": "love_oracle_v1",
        "experiment_assignment": "control",
        "conversion_hook": "conversion_hook_v1",
        "test_traffic": "false",
        "calculation_timezone": "Europe/Moscow",
    }

    projected = project_personal_reading_event(
        OracleProductEvent.READING_PREVIEW_READY.value,
        properties,
        latest_entry,
        subject_id=str(user_id),
    )

    assert projected is not None
    _event, payload = projected
    assert payload["source"] == "daily_horoscope"
    assert payload["experiment_assignment"] == free_preview_experiment_assignment(user_id)
