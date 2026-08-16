"""Regression coverage for conversion-hook cohorts and funnel identity."""

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from app.bot.conversion_hooks import DEFAULT_READING_HOOK, render_grounded_hook
from app.domain.conversion_experiment import (
    CONVERSION_HOOK_EXPERIMENT,
    ConversionHookVariant,
    conversion_experiment_properties,
    conversion_hook_variant,
)


@dataclass(frozen=True, slots=True)
class _Scenario:
    scenario: str
    conditions: tuple[str, ...]


def _uuid_with_last_byte(value: int) -> UUID:
    return UUID(bytes=b"\x00" * 15 + bytes((value,)))


def test_conversion_assignment_is_stable_and_covers_all_three_arms() -> None:
    assert conversion_hook_variant(_uuid_with_last_byte(0)) is ConversionHookVariant.A
    assert conversion_hook_variant(_uuid_with_last_byte(1)) is ConversionHookVariant.B
    assert conversion_hook_variant(_uuid_with_last_byte(2)) is ConversionHookVariant.C
    user_id = _uuid_with_last_byte(254)
    assert conversion_hook_variant(user_id) is conversion_hook_variant(user_id)
    assert conversion_experiment_properties(user_id) == {
        "experiment_key": CONVERSION_HOOK_EXPERIMENT,
        "experiment_variant": conversion_hook_variant(user_id).value,
    }


def test_hook_arms_change_emphasis_without_changing_grounded_content() -> None:
    scenarios = (
        _Scenario("Сценарий один", ("условие один",)),
        _Scenario("Сценарий два", ("условие два",)),
    )
    rendered = {
        variant: render_grounded_hook(scenarios, DEFAULT_READING_HOOK, variant)
        for variant in ConversionHookVariant
    }
    assert len(set(rendered.values())) == 3
    for text in rendered.values():
        assert "Сценарий один" in text
        assert DEFAULT_READING_HOOK.hidden_conditions_line in text
        assert DEFAULT_READING_HOOK.alternative_line in text
        assert DEFAULT_READING_HOOK.unlock_title in text
        for line in DEFAULT_READING_HOOK.unlock_lines:
            assert line in text
        assert "Сценарий два" not in text


def test_persona_preview_wires_the_assigned_arm_into_the_renderer() -> None:
    service_source = Path("app/services/persona_reading.py").read_text(encoding="utf-8")
    renderer_source = Path("app/bot/reading_renderer.py").read_text(encoding="utf-8")
    assert "conversion_variant=conversion_hook_variant(user_id)" in service_source
    assert "outcome.conversion_variant" in renderer_source


def test_billing_projection_uses_the_same_internal_subject_without_private_payload() -> None:
    migration = Path(
        "migrations/versions/20260816_33_link_billing_analytics_subject.py"
    ).read_text(encoding="utf-8")
    assert "SELECT user_id::text" in migration
    assert "FROM payment_orders" in migration
    assert "order_user_id" in migration
    assert "private_text" not in migration
    assert "NEW.payload" in migration
