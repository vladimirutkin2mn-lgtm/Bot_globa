import inspect

import pytest

from app.bot import group_runtime
from app.bot import main as bot_main


def test_group_runtime_installs_upgrades_in_dependency_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        group_runtime,
        "install_group_social_mechanics",
        lambda: calls.append("social"),
    )
    monkeypatch.setattr(
        group_runtime,
        "install_group_compatibility_mechanics",
        lambda: calls.append("compatibility"),
    )
    monkeypatch.setattr(
        group_runtime,
        "install_group_viral_mechanics",
        lambda: calls.append("viral"),
    )
    monkeypatch.setattr(
        group_runtime,
        "install_group_viral_upgrade",
        lambda: calls.append("viral_upgrade"),
    )
    monkeypatch.setattr(
        group_runtime,
        "install_group_p1_08",
        lambda: calls.append("p1_08"),
    )

    group_runtime.install_group_runtime()

    assert calls == ["social", "compatibility", "viral", "viral_upgrade", "p1_08"]


def test_dispatcher_installs_group_runtime_before_registering_group_router() -> None:
    source = inspect.getsource(bot_main.create_dispatcher)

    assert source.index("install_group_runtime()") < source.index(
        "dispatcher.include_router(group_router)"
    )
