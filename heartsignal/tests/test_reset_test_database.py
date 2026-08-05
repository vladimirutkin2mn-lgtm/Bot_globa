"""Safety checks for the CI-only database reset helper."""

import pytest

from scripts.reset_test_database import _validated_test_dsn


def test_accepts_explicit_test_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://user:password@localhost:5432/oracle_test",
    )

    assert _validated_test_dsn() == "postgresql://user:password@localhost:5432/oracle_test"


def test_rejects_database_without_test_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://user:password@localhost:5432/oracle",
    )

    with pytest.raises(RuntimeError, match="_test suffix"):
        _validated_test_dsn()


def test_requires_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="TEST_DATABASE_URL is required"):
        _validated_test_dsn()
