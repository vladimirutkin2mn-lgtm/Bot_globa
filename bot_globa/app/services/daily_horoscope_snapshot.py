"""Persist and reuse one versioned mass daily-horoscope snapshot per civil date."""

import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db.daily_horoscope_models import DailyHoroscopeSnapshotRow
from app.providers.llm.base import LLMClient
from app.providers.llm.factory import create_llm_client
from app.services.daily_horoscope_ai_editor import (
    DAILY_AI_FALLBACK_VERSION,
    DAILY_AI_METHOD_VERSION,
    DailyHoroscopeAIEditor,
)
from app.services.daily_horoscope_editorial import build_editorial_daily_horoscope
from app.services.daily_sky import DAILY_SKY_VERSION, DailyHoroscopeSnapshot

logger = logging.getLogger(__name__)
_HISTORY_DAYS = 60


class DailyHoroscopeSnapshotService:
    """Reuse one shared snapshot per date and keep LLM work out of per-user delivery."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        llm: LLMClient | None = None,
    ) -> None:
        self._sessions = sessions
        if llm is None:
            settings = get_settings()
            # Development/test stubs keep the old deterministic path unless a test explicitly injects LLM.
            llm = None if settings.llm_provider == "stub" else create_llm_client(settings)
        self._editor = DailyHoroscopeAIEditor(llm) if llm is not None else None

    async def get_or_create(self, forecast_date: date) -> DailyHoroscopeSnapshot:
        async with self._sessions() as session:
            existing = await session.get(DailyHoroscopeSnapshotRow, forecast_date)
            if existing is not None:
                snapshot = _snapshot(existing)
                if _is_current(snapshot):
                    return snapshot

        history = await self._history(forecast_date)
        generated = await self._generate(forecast_date, history)
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

    async def _history(self, forecast_date: date) -> tuple[DailyHoroscopeSnapshot, ...]:
        start = forecast_date - timedelta(days=_HISTORY_DAYS)
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(DailyHoroscopeSnapshotRow)
                    .where(
                        DailyHoroscopeSnapshotRow.forecast_date >= start,
                        DailyHoroscopeSnapshotRow.forecast_date < forecast_date,
                    )
                    .order_by(DailyHoroscopeSnapshotRow.forecast_date.desc())
                )
            ).all()
        snapshots: list[DailyHoroscopeSnapshot] = []
        for row in rows:
            try:
                snapshots.append(_snapshot(row))
            except (TypeError, ValueError):
                logger.warning("daily_horoscope_history_snapshot_invalid date=%s", row.forecast_date)
        return tuple(snapshots)

    async def _generate(
        self,
        forecast_date: date,
        history: tuple[DailyHoroscopeSnapshot, ...],
    ) -> DailyHoroscopeSnapshot:
        if self._editor is not None:
            try:
                generated = await self._editor.generate(forecast_date, history)
                logger.info(
                    "daily_horoscope_ai_snapshot_generated date=%s history_days=%s",
                    forecast_date,
                    len(history),
                )
                return generated
            except Exception:
                # The mass daily must remain deliverable even if the model or quality gate fails.
                logger.exception("daily_horoscope_ai_editor_failed date=%s; using fallback", forecast_date)

        fallback = build_editorial_daily_horoscope(forecast_date)
        return DailyHoroscopeSnapshot(
            forecast_date=fallback.forecast_date,
            sky_digest=fallback.sky_digest,
            theme=fallback.theme,
            signs=fallback.signs,
            sky_version=fallback.sky_version,
            methodology_version=DAILY_AI_FALLBACK_VERSION,
        )


def _is_current(snapshot: DailyHoroscopeSnapshot) -> bool:
    return snapshot.sky_version == DAILY_SKY_VERSION and snapshot.methodology_version in {
        DAILY_AI_METHOD_VERSION,
        DAILY_AI_FALLBACK_VERSION,
    }


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
