"""Environment-backed controls for limited oracle release."""

import re
from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_CODE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class OracleReleaseSettings(BaseSettings):
    """Operational release controls isolated from product and billing settings."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    oracle_enabled: bool = True
    oracle_rollout_percentage: int = Field(default=100, ge=0, le=100)
    oracle_rollout_seed: str = "oracle-rollout-v1"
    oracle_disabled_personas: str = ""
    oracle_disabled_engines: str = ""
    oracle_generation_rate_limit: int = Field(default=0, ge=0)
    oracle_generation_rate_window_seconds: int = Field(default=60, gt=0)
    oracle_daily_spend_cap_microusd: int = Field(default=0, ge=0)
    oracle_max_reserved_cost_microusd_per_reading: int = Field(default=0, ge=0)

    @field_validator("oracle_rollout_seed")
    @classmethod
    def rollout_seed_is_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("oracle rollout seed cannot be empty")
        return cleaned

    @field_validator("oracle_disabled_personas", "oracle_disabled_engines")
    @classmethod
    def kill_switch_codes_are_valid(cls, value: str) -> str:
        codes = [code.strip() for code in value.split(",") if code.strip()]
        if any(_CODE.fullmatch(code) is None for code in codes):
            raise ValueError("oracle kill switch contains an invalid code")
        return ",".join(codes)

    @model_validator(mode="after")
    def validate_spend_cap(self) -> "OracleReleaseSettings":
        if self.oracle_daily_spend_cap_microusd == 0:
            return self
        reservation = self.oracle_max_reserved_cost_microusd_per_reading
        if reservation <= 0:
            raise ValueError("oracle spend cap requires a positive per-reading reservation")
        if reservation > self.oracle_daily_spend_cap_microusd:
            raise ValueError("oracle per-reading reservation cannot exceed the daily spend cap")
        return self


@lru_cache
def get_oracle_release_settings() -> OracleReleaseSettings:
    return OracleReleaseSettings()
