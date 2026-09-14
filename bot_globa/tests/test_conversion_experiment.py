from uuid import UUID

import pytest

from app.domain import conversion_experiment
from app.domain.conversion_experiment import FreePreviewVariant


def test_free_preview_assignment_is_stable_while_experiment_is_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(conversion_experiment, "FREE_PREVIEW_EXPERIMENT_ENABLED", True)
    user_id = UUID("12345678-1234-5678-1234-567812345678")

    first = conversion_experiment.free_preview_variant(user_id)
    second = conversion_experiment.free_preview_variant(user_id)

    assert first is second
    assert first in {FreePreviewVariant.BASELINE, FreePreviewVariant.COMPLETE}


def test_free_preview_stop_control_freezes_every_user_on_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(conversion_experiment, "FREE_PREVIEW_EXPERIMENT_ENABLED", False)
    monkeypatch.setattr(
        conversion_experiment,
        "FREE_PREVIEW_DEFAULT_VARIANT",
        FreePreviewVariant.COMPLETE,
    )

    user_ids = (
        UUID("00000000-0000-0000-0000-000000000001"),
        UUID("12345678-1234-5678-1234-567812345678"),
        UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
    )

    assert {conversion_experiment.free_preview_variant(user_id) for user_id in user_ids} == {
        FreePreviewVariant.COMPLETE
    }
    assert {
        conversion_experiment.free_preview_experiment_assignment(user_id) for user_id in user_ids
    } == {"free_preview_v1:complete"}
