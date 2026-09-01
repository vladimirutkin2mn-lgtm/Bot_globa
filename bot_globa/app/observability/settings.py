"""Configuration isolated to analytics, admin metrics and error reporting."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ObservabilitySettings(BaseSettings):
    """Validated observability settings loaded from the same environment file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["local", "test", "staging", "production"] = "local"
    analytics_backend: Literal["noop", "postgres"] = "noop"
    error_reporting_backend: Literal["noop", "logging"] = "logging"
    admin_metrics_enabled: bool = False
    admin_api_token: SecretStr = SecretStr("")
    llm_input_cost_usd_per_million_tokens: float | None = Field(default=None, ge=0)
    llm_output_cost_usd_per_million_tokens: float | None = Field(default=None, ge=0)
    langsmith_enabled: bool = False
    langsmith_api_key: SecretStr = SecretStr("")
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_project: str = "numa-oracle"
    langsmith_workspace_id: str = ""
    langsmith_trace_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    langsmith_max_pending_traces: int = Field(default=100, ge=1, le=10_000)

    @field_validator("langsmith_endpoint")
    @classmethod
    def normalize_langsmith_endpoint(cls, value: str) -> str:
        endpoint = value.strip().rstrip("/")
        if not endpoint.startswith(("http://", "https://")):
            raise ValueError("LangSmith endpoint must be HTTP(S)")
        return endpoint

    @model_validator(mode="after")
    def validate_admin_auth(self) -> "ObservabilitySettings":
        if (self.llm_input_cost_usd_per_million_tokens is None) != (
            self.llm_output_cost_usd_per_million_tokens is None
        ):
            raise ValueError("LLM input and output cost rates must be configured together")
        if self.langsmith_enabled:
            if not self.langsmith_api_key.get_secret_value().strip():
                raise ValueError("enabled LangSmith tracing requires an API key")
            if not self.langsmith_project.strip():
                raise ValueError("enabled LangSmith tracing requires a project")
            if self.app_env == "production" and not self.langsmith_endpoint.startswith("https://"):
                raise ValueError("production LangSmith tracing requires HTTPS")
        if not self.admin_metrics_enabled:
            return self
        token = self.admin_api_token.get_secret_value().strip()
        if not token:
            raise ValueError("enabled admin metrics require a token")
        if self.app_env == "production" and (
            len(token) < 32 or token.lower() in {"change-me", "changeme", "development-only-token"}
        ):
            raise ValueError("production admin metrics require a strong token")
        return self


@lru_cache
def get_observability_settings() -> ObservabilitySettings:
    return ObservabilitySettings()
