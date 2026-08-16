"""Persist and reuse one versioned mass daily-horoscope snapshot per civil date."""

from datetime import date

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.daily_horoscope_models import DailyHoroscopeSnapshotRow
from app.services.daily_horoscope_editorial import (
    DAILY_EDITORIAL_METHOD_VERSION,
    build_editorial_daily_horoscope,
)
from app.services.daily_sky import DAILY_SKY_VERSION, DailyHoroscopeSnapshot


class DailyHoroscopeSnapshotService:
    """Reuse current content for a date and replace snapshots from obsolete methodology."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get_or_create(self, forecast_date: date) -> DailyHoroscopeSnapshot:
        async with self._sessions() as session:
            existing = await session.get(DailyHoroscopeSnapshotRow, forecast_date)
            if existing is not None:
                snapshot = _snapshot(existing)
                if _is_current(snapshot):
                    return snapshot

        generated = build_editorial_daily_horoscope(forecast_date)
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


def _is_current(snapshot: DailyHoroscopeSnapshot) -> bool:
    return (
        snapshot.sky_version == DAILY_SKY_VERSION
        and snapshot.methodology_version == DAILY_EDITORIAL_METHOD_VERSION
    )


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
