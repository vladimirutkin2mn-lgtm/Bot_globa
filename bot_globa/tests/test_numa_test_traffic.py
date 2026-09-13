"""Manual and synthetic Numa sessions must be explicitly markable as test traffic."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.observability.settings import ObservabilitySettings
from app.providers.analytics_postgres import _mark_test_traffic


def test_observability_settings_normalize_internal_test_user_ids() -> None:
    first, second = uuid4(), uuid4()

    settings = ObservabilitySettings(
        analytics_test_user_ids=f" {first}, {second}, {first} ",
    )

    assert settings.analytics_test_user_ids == f"{first},{second}"
    assert settings.analytics_test_users == frozenset({str(first), str(second)})


def test_observability_settings_reject_non_uuid_test_identity() -> None:
    with pytest.raises(ValidationError, match="analytics test user ids must be UUIDs"):
        ObservabilitySettings(analytics_test_user_ids="telegram-user-123")


def test_configured_subject_is_marked_without_changing_other_dimensions() -> None:
    user_id = str(uuid4())
    properties = {
        "event_version": "numa-product-funnel-v1",
        "entity_id": str(uuid4()),
        "flow": "personal",
        "source": "normal_start",
        "scenario_version": "personal_oracle_v1",
        "experiment_assignment": "control",
        "conversion_hook": "conversion_hook_v1",
        "test_traffic": "false",
        "calculation_timezone": "Europe/Moscow",
    }

    marked = _mark_test_traffic(properties, user_id, frozenset({user_id}))

    assert marked == {**properties, "test_traffic": "true"}
    assert properties["test_traffic"] == "false"


def test_ordinary_subject_remains_decision_traffic() -> None:
    properties = {"test_traffic": "false", "flow": "daily"}

    marked = _mark_test_traffic(properties, str(uuid4()), frozenset({str(uuid4())}))

    assert marked == properties
