"""Persist and reuse one versioned mass daily-horoscope snapshot per civil date."""

import asyncio
import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.daily_horoscope_models import DailyHoroscopeSnapshotRow
from app.services.daily_horoscope_editorial import (
    DAILY_EDITORIAL_METHOD_VERSION,
    build_editorial_daily_horoscope,
)
from app.services.daily_horoscope_generation import (
    DAILY_AI_CURRENT_METHODS,
    DAILY_HISTORY_DAYS,
    DailyHoroscopeGenerationService,
)
from app.services.daily_sky import DAILY_SKY_VERSION, DailyHoroscopeSnapshot

logger = logging.getLogger(__name__)


class DailyHoroscopeSnapshotService:
    """Reuse one snapshot per date and let the delivery worker upgrade it to AI editorial."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        generator: DailyHoroscopeGenerationService | None = None,
    ) -> None:
        self._sessions = sessions
        self._generator = generator

    async def get_or_create(self, forecast_date: date) -> DailyHoroscopeSnapshot:
        async with self._sessions() as session:
            existing = await session.get(DailyHoroscopeSnapshotRow, forecast_date)
            if existing is not None:
                snapshot = _snapshot(existing)
                if self._is_current(snapshot):
                    return snapshot

        generated = await self._generate(forecast_date)
        values = {
            "forecast_date": forecast_date,
            "sky_version": generated.sky_version,
            "methodology_version": generated.methodology_version,
            "sky_digest": generated.sky_digest,
            "payload": generated.payload(),
        }
        async with self._sessions.begin() as session:
            await session.execute(
                insert(DailyHoroscopeSnapshotRow)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=["forecast_date"],
                    set_={key: value for key, value in values.items() if key != "forecast_date"},
                )
            )
        async with self._sessions() as session:
            stored = await session.get(DailyHoroscopeSnapshotRow, forecast_date)
            if stored is None:
                raise RuntimeError("daily horoscope snapshot upsert did not persist")
            return _snapshot(stored)

    def _is_current(self, snapshot: DailyHoroscopeSnapshot) -> bool:
        if snapshot.sky_version != DAILY_SKY_VERSION:
            return False
        if self._generator is not None:
            return snapshot.methodology_version in self._generator.methodology_versions
        return snapshot.methodology_version in {
            DAILY_EDITORIAL_METHOD_VERSION,
            *DAILY_AI_CURRENT_METHODS,
        }

    async def _generate(self, forecast_date: date) -> DailyHoroscopeSnapshot:
        if self._generator is None:
            return build_editorial_daily_horoscope(forecast_date)
        history = await self._recent_history(forecast_date)
        try:
            return await self._generator.generate(forecast_date, history)
        except asyncio.CancelledError:
            raise
        except Exception:
            # One failed provider call must never turn the 08:00 retention surface off.
            # Persist the deterministic fallback for this date so every recipient sees the
            # same content and subsequent users do not hammer a failing provider.
            logger.exception("daily_horoscope_ai_editor_failed_using_fallback")
            return self._generator.fallback(forecast_date)

    async def _recent_history(self, forecast_date: date) -> tuple[DailyHoroscopeSnapshot, ...]:
        async with self._sessions() as session:
            rows = list(
                (
                    await session.scalars(
                        select(DailyHoroscopeSnapshotRow)
                        .where(DailyHoroscopeSnapshotRow.forecast_date < forecast_date)
                        .order_by(DailyHoroscopeSnapshotRow.forecast_date.desc())
                        .limit(DAILY_HISTORY_DAYS)
                    )
                ).all()
            )
        history: list[DailyHoroscopeSnapshot] = []
        for row in rows:
            try:
                history.append(_snapshot(row))
            except ValueError:
                logger.warning(
                    "daily_horoscope_history_snapshot_invalid date=%s",
                    row.forecast_date,
                )
        return tuple(history)


def _snapshot(row: DailyHoroscopeSnapshotRow) -> DailyHoroscopeSnapshot:
    snapshot = DailyHoroscopeSnapshot.from_payload(row.payload)
    if snapshot.forecast_date != row.forecast_date:
        raise ValueError("daily horoscope snapshot date mismatch")
    if snapshot.sky_version != row.sky_version:
        raise ValueError("daily horoscope sky version mismatch")
    if snapshot.methodology_version != row.methodology_version:
        raise ValueError("daily horoscope methodology version mismatch")
    if snapshot.sky_digest != row.sky_digest:
        raise ValueError("daily horoscope sky digest mismatch")
    return snapshot
