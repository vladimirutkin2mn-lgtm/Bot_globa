"""Fail-closed controls for a limited oracle release."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from enum import StrEnum
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.reading_models import Reading
from app.domain.reading import ReadingDraftRequest
from app.release_settings import OracleReleaseSettings

_ADMISSION_LOCK_KEY = 6_040_001


class OracleReleaseDecisionCode(StrEnum):
    ALLOWED = "allowed"
    ORACLE_DISABLED = "oracle_disabled"
    ROLLOUT_EXCLUDED = "rollout_excluded"
    PERSONA_DISABLED = "persona_disabled"
    ENGINE_DISABLED = "engine_disabled"
    RATE_LIMITED = "rate_limited"
    SPEND_CAP_REACHED = "spend_cap_reached"


@dataclass(frozen=True, slots=True)
class OracleReleaseDecision:
    code: OracleReleaseDecisionCode

    @property
    def allowed(self) -> bool:
        return self.code is OracleReleaseDecisionCode.ALLOWED

    @property
    def failure_code(self) -> str:
        return f"release_{self.code.value}"


class OracleReleaseControls:
    """Evaluate rollout and operational limits without inspecting private content."""

    def __init__(
        self,
        *,
        enabled: bool,
        rollout_percentage: int,
        rollout_seed: str,
        disabled_personas: frozenset[str],
        disabled_engines: frozenset[str],
        generation_rate_limit: int,
        generation_rate_window_seconds: int,
        daily_spend_cap_microusd: int,
        max_reserved_cost_microusd_per_reading: int,
    ) -> None:
        if not 0 <= rollout_percentage <= 100:
            raise ValueError("oracle rollout percentage must be between 0 and 100")
        if not rollout_seed.strip():
            raise ValueError("oracle rollout seed cannot be empty")
        if generation_rate_limit < 0:
            raise ValueError("oracle generation rate limit cannot be negative")
        if generation_rate_window_seconds <= 0:
            raise ValueError("oracle generation rate window must be positive")
        if daily_spend_cap_microusd < 0:
            raise ValueError("oracle daily spend cap cannot be negative")
        if max_reserved_cost_microusd_per_reading < 0:
            raise ValueError("oracle reserved reading cost cannot be negative")
        if daily_spend_cap_microusd > 0 and max_reserved_cost_microusd_per_reading <= 0:
            raise ValueError("oracle spend cap requires a positive per-reading reservation")
        if (
            daily_spend_cap_microusd > 0
            and max_reserved_cost_microusd_per_reading > daily_spend_cap_microusd
        ):
            raise ValueError("oracle per-reading reservation cannot exceed the daily spend cap")
        self._enabled = enabled
        self._rollout_percentage = rollout_percentage
        self._rollout_seed = rollout_seed.strip()
        self._disabled_personas = disabled_personas
        self._disabled_engines = disabled_engines
        self._generation_rate_limit = generation_rate_limit
        self._generation_rate_window_seconds = generation_rate_window_seconds
        self._daily_spend_cap_microusd = daily_spend_cap_microusd
        self._max_reserved_cost_microusd_per_reading = max_reserved_cost_microusd_per_reading

    @classmethod
    def from_settings(cls, settings: OracleReleaseSettings) -> OracleReleaseControls:
        return cls(
            enabled=settings.oracle_enabled,
            rollout_percentage=settings.oracle_rollout_percentage,
            rollout_seed=settings.oracle_rollout_seed,
            disabled_personas=_csv_codes(settings.oracle_disabled_personas),
            disabled_engines=_csv_codes(settings.oracle_disabled_engines),
            generation_rate_limit=settings.oracle_generation_rate_limit,
            generation_rate_window_seconds=settings.oracle_generation_rate_window_seconds,
            daily_spend_cap_microusd=settings.oracle_daily_spend_cap_microusd,
            max_reserved_cost_microusd_per_reading=(
                settings.oracle_max_reserved_cost_microusd_per_reading
            ),
        )

    def generation_decision(
        self,
        user_id: UUID,
        *,
        persona_code: str,
        engine_version: str,
    ) -> OracleReleaseDecision:
        """Re-check static switches before expensive work begins."""

        if not self._enabled:
            return OracleReleaseDecision(OracleReleaseDecisionCode.ORACLE_DISABLED)
        if persona_code in self._disabled_personas:
            return OracleReleaseDecision(OracleReleaseDecisionCode.PERSONA_DISABLED)
        if engine_version in self._disabled_engines:
            return OracleReleaseDecision(OracleReleaseDecisionCode.ENGINE_DISABLED)
        if not self._included_in_rollout(user_id):
            return OracleReleaseDecision(OracleReleaseDecisionCode.ROLLOUT_EXCLUDED)
        return OracleReleaseDecision(OracleReleaseDecisionCode.ALLOWED)

    async def authorize_draft(
        self,
        session: AsyncSession,
        user_id: UUID,
        request: ReadingDraftRequest,
        *,
        now: datetime | None = None,
    ) -> OracleReleaseDecision:
        """Atomically admit a new Reading under cross-worker release limits."""

        static = self.generation_decision(
            user_id,
            persona_code=request.persona_code,
            engine_version=request.engine_version,
        )
        if not static.allowed:
            return static
        if self._generation_rate_limit == 0 and self._daily_spend_cap_microusd == 0:
            return static

        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            raise ValueError("oracle release admission time must be timezone-aware")
        await session.execute(select(func.pg_advisory_xact_lock(_ADMISSION_LOCK_KEY)))

        if self._generation_rate_limit > 0:
            cutoff = current - timedelta(seconds=self._generation_rate_window_seconds)
            recent_count = await session.scalar(
                select(func.count())
                .select_from(Reading)
                .where(Reading.user_id == user_id, Reading.created_at >= cutoff)
            )
            if int(recent_count or 0) >= self._generation_rate_limit:
                return OracleReleaseDecision(OracleReleaseDecisionCode.RATE_LIMITED)

        if self._daily_spend_cap_microusd > 0:
            day_start = datetime.combine(current.astimezone(UTC).date(), time.min, tzinfo=UTC)
            daily_count = await session.scalar(
                select(func.count()).select_from(Reading).where(Reading.created_at >= day_start)
            )
            reserved_after_admission = (int(daily_count or 0) + 1) * (
                self._max_reserved_cost_microusd_per_reading
            )
            if reserved_after_admission > self._daily_spend_cap_microusd:
                return OracleReleaseDecision(OracleReleaseDecisionCode.SPEND_CAP_REACHED)

        return OracleReleaseDecision(OracleReleaseDecisionCode.ALLOWED)

    def _included_in_rollout(self, user_id: UUID) -> bool:
        if self._rollout_percentage <= 0:
            return False
        if self._rollout_percentage >= 100:
            return True
        digest = hashlib.sha256(f"{self._rollout_seed}:{user_id}".encode()).digest()
        bucket = int.from_bytes(digest[:8], "big") % 100
        return bucket < self._rollout_percentage


def _csv_codes(value: str) -> frozenset[str]:
    return frozenset(code.strip() for code in value.split(",") if code.strip())
