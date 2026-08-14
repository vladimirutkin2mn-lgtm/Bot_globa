"""Production runtime policy and bounded maintenance settings."""

import re
from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config import Settings

_TELEGRAM_WEBHOOK_PATH = "/telegram/webhook"
_TELEGRAM_SECRET = re.compile(r"[A-Za-z0-9_-]{1,256}\Z")
_TELEGRAM_BOT_USERNAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{4,31}\Z")


class DeploymentSettings(BaseSettings):
    """Operational settings kept separate from product and billing configuration."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_username: str = ""
    telegram_webhook_max_bytes: int = Field(default=1_048_576, gt=0, le=10_485_760)
    telegram_update_lease_seconds: int = Field(default=300, ge=30, le=3600)
    telegram_update_retry_base_seconds: int = Field(default=5, ge=1, le=3600)
    telegram_update_max_attempts: int = Field(default=8, ge=1, le=100)
    telegram_worker_idle_seconds: float = Field(default=0.5, gt=0, le=60)
    daily_horoscope_lease_seconds: int = Field(default=120, ge=30, le=3600)
    daily_horoscope_worker_idle_seconds: float = Field(default=5, gt=0, le=60)
    # The whole active base shares one 08:00 local schedule, so the digest is a broadcast
    # rather than a trickle. Pace it below Telegram's ~30 messages/second global ceiling and
    # keep a retry budget for the 429s that a burst still produces.
    daily_horoscope_send_interval_seconds: float = Field(default=0.05, ge=0, le=5)
    daily_horoscope_send_max_attempts: int = Field(default=4, ge=1, le=10)
    maintenance_interval_seconds: float = Field(default=300, gt=0)
    maintenance_batch_size: int = Field(default=100, ge=1, le=10_000)

    @field_validator("telegram_bot_username")
    @classmethod
    def valid_telegram_bot_username(cls, value: str) -> str:
        normalized = value.strip().removeprefix("@")
        if not normalized:
            return ""
        if _TELEGRAM_BOT_USERNAME.fullmatch(normalized) is None:
            raise ValueError("Telegram bot username must be a valid public username")
        if not normalized.casefold().endswith("bot"):
            raise ValueError("Telegram bot username must end with 'bot'")
        return normalized


def validate_telegram_webhook(settings: Settings) -> None:
    """Fail closed for webhook deployments without exposing secret values."""
    if not settings.webhook_enabled:
        return
    parsed = urlsplit(settings.telegram_webhook_url)
    if parsed.path != _TELEGRAM_WEBHOOK_PATH or parsed.query or parsed.fragment:
        raise ValueError(f"Telegram webhook URL must end with {_TELEGRAM_WEBHOOK_PATH}")
    secret = settings.telegram_webhook_secret.get_secret_value()
    if _TELEGRAM_SECRET.fullmatch(secret) is None:
        raise ValueError("Telegram webhook secret must use 1-256 safe ASCII characters")
    if settings.app_env == "production":
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("production Telegram webhook requires a public HTTPS URL")
        if len(secret) < 32:
            raise ValueError("production Telegram webhook requires a strong secret")


def validate_production_providers(settings: Settings) -> None:
    """Refuse to serve production from a development stub.

    Both provider settings default to something that answers without a network, which is
    what tests and local development need — and which production accepted silently. A
    stub geocoder knows forty-four cities and a stub model returns a fixture, so the
    deployment reports itself healthy while the product cannot do its job. It is better
    to fail at boot, loudly, than to answer users with "временно недоступно".
    """

    if settings.app_env != "production":
        return
    stubs = [
        name
        for name, value in (
            ("LLM_PROVIDER", settings.llm_provider),
            ("GEOCODING_PROVIDER", settings.geocoding_provider),
        )
        if value == "stub"
    ]
    if stubs:
        raise ValueError(f"production must not run on development stubs: {', '.join(stubs)}")


def validate_telegram_worker(settings: Settings, deployment: DeploymentSettings) -> None:
    """Keep a live analysis inside its claim lease under the configured retry budget."""
    if not settings.webhook_enabled:
        raise ValueError("Telegram update worker requires webhook mode")
    llm_calls = 1 + settings.llm_max_repair_attempts
    worst_case_seconds = (
        settings.llm_timeout_seconds * settings.llm_max_transport_attempts * llm_calls
    )
    required_lease = int(worst_case_seconds) + 30
    if deployment.telegram_update_lease_seconds < required_lease:
        raise ValueError(
            "Telegram update lease is shorter than the configured LLM execution budget"
        )


@lru_cache
def get_deployment_settings() -> DeploymentSettings:
    return DeploymentSettings()
