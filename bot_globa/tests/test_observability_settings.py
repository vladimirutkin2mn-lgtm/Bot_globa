"""Configuration coverage for analytics, error reporting and admin metrics."""

import pytest
from pydantic import SecretStr, ValidationError

from app.observability.settings import ObservabilitySettings


def test_postgres_analytics_backend_is_supported() -> None:
    settings = ObservabilitySettings(app_env="production", analytics_backend="postgres")
    assert settings.analytics_backend == "postgres"


def test_llm_cost_rates_must_be_configured_together_and_non_negative() -> None:
    with pytest.raises(ValidationError):
        ObservabilitySettings(llm_input_cost_usd_per_million_tokens=2.0)
    with pytest.raises(ValidationError):
        ObservabilitySettings(llm_output_cost_usd_per_million_tokens=6.0)
    with pytest.raises(ValidationError):
        ObservabilitySettings(
            llm_input_cost_usd_per_million_tokens=-1.0,
            llm_output_cost_usd_per_million_tokens=6.0,
        )

    settings = ObservabilitySettings(
        llm_input_cost_usd_per_million_tokens=2.0,
        llm_output_cost_usd_per_million_tokens=6.0,
    )
    assert settings.llm_input_cost_usd_per_million_tokens == 2.0
    assert settings.llm_output_cost_usd_per_million_tokens == 6.0


def test_enabled_admin_metrics_require_token() -> None:
    with pytest.raises(ValidationError):
        ObservabilitySettings(app_env="test", admin_metrics_enabled=True)


def test_production_admin_metrics_reject_placeholder_or_short_tokens() -> None:
    for token in ("change-me", "short-token"):
        with pytest.raises(ValidationError):
            ObservabilitySettings(
                app_env="production",
                admin_metrics_enabled=True,
                admin_api_token=SecretStr(token),
            )


def test_production_admin_metrics_accept_strong_secret_without_exposing_it() -> None:
    secret = "admin-production-secret-0123456789abcdef"
    settings = ObservabilitySettings(
        app_env="production",
        analytics_backend="postgres",
        admin_metrics_enabled=True,
        admin_api_token=SecretStr(secret),
    )
    rendered = f"{settings!r}\n{settings}\n{settings.model_dump_json()}"
    assert settings.analytics_backend == "postgres"
    assert secret not in rendered
    assert "**********" in rendered


def test_enabled_langsmith_requires_secret_and_project() -> None:
    with pytest.raises(ValidationError):
        ObservabilitySettings(langsmith_enabled=True)
    with pytest.raises(ValidationError):
        ObservabilitySettings(
            langsmith_enabled=True,
            langsmith_api_key=SecretStr("test-key"),
            langsmith_project="   ",
        )


def test_production_langsmith_requires_https_and_keeps_key_secret() -> None:
    with pytest.raises(ValidationError):
        ObservabilitySettings(
            app_env="production",
            langsmith_enabled=True,
            langsmith_api_key=SecretStr("langsmith-production-secret"),
            langsmith_endpoint="http://langsmith.internal",
        )

    secret = "langsmith-production-secret"
    settings = ObservabilitySettings(
        app_env="production",
        langsmith_enabled=True,
        langsmith_api_key=SecretStr(secret),
        langsmith_endpoint="https://eu.api.smith.langchain.com/",
        langsmith_project="numa-production",
    )
    rendered = f"{settings!r}\n{settings}\n{settings.model_dump_json()}"
    assert settings.langsmith_endpoint == "https://eu.api.smith.langchain.com"
    assert secret not in rendered
    assert "**********" in rendered
