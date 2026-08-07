"""Limited-release rollout and configuration contracts."""

from uuid import UUID

import pytest
from pydantic import ValidationError

from app.release_settings import OracleReleaseSettings
from app.services.oracle_release_controls import (
    OracleReleaseControls,
    OracleReleaseDecisionCode,
)

_DEFAULT_USER_ID = UUID(int=1)


def _controls(
    *,
    enabled: bool = True,
    rollout_percentage: int = 100,
    rollout_seed: str = "release-test-v1",
    disabled_personas: frozenset[str] = frozenset(),
    disabled_engines: frozenset[str] = frozenset(),
    generation_rate_limit: int = 0,
    generation_rate_window_seconds: int = 60,
    daily_spend_cap_microusd: int = 0,
    max_reserved_cost_microusd_per_reading: int = 0,
) -> OracleReleaseControls:
    return OracleReleaseControls(
        enabled=enabled,
        rollout_percentage=rollout_percentage,
        rollout_seed=rollout_seed,
        disabled_personas=disabled_personas,
        disabled_engines=disabled_engines,
        generation_rate_limit=generation_rate_limit,
        generation_rate_window_seconds=generation_rate_window_seconds,
        daily_spend_cap_microusd=daily_spend_cap_microusd,
        max_reserved_cost_microusd_per_reading=max_reserved_cost_microusd_per_reading,
    )


def _decision(
    controls: OracleReleaseControls,
    user_id: UUID = _DEFAULT_USER_ID,
    *,
    persona_code: str = "tarot_reader",
    engine_version: str = "symbolic-v1",
) -> OracleReleaseDecisionCode:
    return controls.generation_decision(
        user_id,
        persona_code=persona_code,
        engine_version=engine_version,
    ).code


def test_default_release_controls_allow_existing_oracle_behavior() -> None:
    settings = OracleReleaseSettings(_env_file=None)
    controls = OracleReleaseControls.from_settings(settings)

    assert _decision(controls) is OracleReleaseDecisionCode.ALLOWED


def test_global_persona_and_engine_kill_switches_fail_closed() -> None:
    assert _decision(_controls(enabled=False)) is OracleReleaseDecisionCode.ORACLE_DISABLED
    assert (
        _decision(
            _controls(disabled_personas=frozenset({"love_oracle"})),
            persona_code="love_oracle",
        )
        is OracleReleaseDecisionCode.PERSONA_DISABLED
    )
    assert (
        _decision(
            _controls(disabled_engines=frozenset({"astrology-calculation-v1"})),
            persona_code="astrologer",
            engine_version="astrology-calculation-v1",
        )
        is OracleReleaseDecisionCode.ENGINE_DISABLED
    )


def test_rollout_is_deterministic_and_percentage_bounded() -> None:
    user_id = UUID("12345678-1234-5678-1234-567812345678")
    excluded = _controls(rollout_percentage=0)
    included = _controls(rollout_percentage=100)
    partial = _controls(rollout_percentage=50)

    assert _decision(excluded, user_id) is OracleReleaseDecisionCode.ROLLOUT_EXCLUDED
    assert _decision(included, user_id) is OracleReleaseDecisionCode.ALLOWED
    first = _decision(partial, user_id)
    assert _decision(partial, user_id) is first

    cohort = {_decision(partial, UUID(int=index)) for index in range(1, 201)}
    assert cohort == {
        OracleReleaseDecisionCode.ALLOWED,
        OracleReleaseDecisionCode.ROLLOUT_EXCLUDED,
    }


def test_release_settings_normalize_kill_switch_lists() -> None:
    settings = OracleReleaseSettings(
        _env_file=None,
        oracle_disabled_personas=" astrologer, love_oracle ",
        oracle_disabled_engines=" astrology-calculation-v1 , symbolic-v1 ",
    )
    controls = OracleReleaseControls.from_settings(settings)

    assert (
        _decision(controls, persona_code="love_oracle")
        is OracleReleaseDecisionCode.PERSONA_DISABLED
    )
    assert (
        _decision(controls, engine_version="symbolic-v1")
        is OracleReleaseDecisionCode.ENGINE_DISABLED
    )


def test_release_settings_reject_invalid_kill_switch_code() -> None:
    with pytest.raises(ValidationError):
        OracleReleaseSettings(_env_file=None, oracle_disabled_personas="tarot reader")


def test_spend_cap_requires_valid_reservation() -> None:
    with pytest.raises(ValidationError):
        OracleReleaseSettings(
            _env_file=None,
            oracle_daily_spend_cap_microusd=1_000,
            oracle_max_reserved_cost_microusd_per_reading=0,
        )
    with pytest.raises(ValidationError):
        OracleReleaseSettings(
            _env_file=None,
            oracle_daily_spend_cap_microusd=1_000,
            oracle_max_reserved_cost_microusd_per_reading=1_001,
        )
