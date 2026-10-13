"""Persist and reuse one versioned mass daily-horoscope snapshot per civil date."""

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.daily_horoscope_models import DailyHoroscopeSnapshotRow
from app.providers.llm.base import LLMClient
from app.services.daily_horoscope_ai import (
    DAILY_AI_FALLBACK_METHOD_VERSION,
    DAILY_AI_METHOD_VERSION,
    DAILY_HISTORY_DAYS,
    DailyHoroscopeAIEditor,
)
from app.services.daily_horoscope_editorial import (
    DAILY_EDITORIAL_METHOD_VERSION,
    build_editorial_daily_horoscope,
)
from app.services.daily_horoscope_facts import build_daily_horoscope_facts
from app.services.daily_sky import DAILY_SKY_VERSION, DailyHoroscopeSnapshot

logger = logging.getLogger(__name__)


class DailyHoroscopeSnapshotService:
    """Reuse one date snapshot; optionally AI-edit it once before the first delivery."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        llm: LLMClient | None = None,
    ) -> None:
        self._sessions = sessions
        self._editor = DailyHoroscopeAIEditor(llm) if llm is not None else None

    async def get_or_create(self, forecast_date: date) -> DailyHoroscopeSnapshot:
        async with self._sessions() as session:
            existing = await session.get(DailyHoroscopeSnapshotRow, forecast_date)
            if existing is not None:
                snapshot = _snapshot(existing)
                if _is_current(snapshot, ai_enabled=self._editor is not None):
                    return snapshot

        editorial_meta: dict[str, dict[str, str]] = {}
        if self._editor is None:
            generated = build_editorial_daily_horoscope(forecast_date)
        else:
            # The model sees structured application-owned calculation facts, never the old
            # phrase-library editorial layer. That keeps calculation in code and language in LLM.
            facts = build_daily_horoscope_facts(forecast_date)
            history = await self._recent_history(forecast_date)
            try:
                ai_result = await self._editor.generate(facts, history)
            except Exception:
                # A mass daily must never disappear because a model/provider/editorial
                # validation failed. Persist the fallback methodology for the date so the
                # next recipient does not trigger another LLM call in the same broadcast.
                logger.exception("daily_horoscope_ai_editor_failed fallback=deterministic")
                generated = _fallback_snapshot(build_editorial_daily_horoscope(forecast_date))
            else:
                generated = ai_result.snapshot
                editorial_meta = ai_result.editorial_meta

        payload = generated.payload()
        if editorial_meta:
            payload["editorial_meta"] = editorial_meta
        values = {
            "forecast_date": forecast_date,
            "sky_version": generated.sky_version,
            "methodology_version": generated.methodology_version,
            "sky_digest": generated.sky_digest,
            "payload": payload,
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

    async def _recent_history(self, forecast_date: date) -> dict[str, list[dict[str, str]]]:
        """Read the last 60 persisted sign texts; no separate history table is required."""

        async with self._sessions() as session:
            rows = (
                (
                    await session.execute(
                        select(DailyHoroscopeSnapshotRow)
                        .where(DailyHoroscopeSnapshotRow.forecast_date < forecast_date)
                        .order_by(DailyHoroscopeSnapshotRow.forecast_date.desc())
                        .limit(DAILY_HISTORY_DAYS)
                    )
                )
                .scalars()
                .all()
            )
        history: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            payload = row.payload if isinstance(row.payload, dict) else {}
            raw_meta = payload.get("editorial_meta")
            meta = raw_meta if isinstance(raw_meta, dict) else {}
            raw_signs = payload.get("signs")
            if not isinstance(raw_signs, list):
                continue
            for item in raw_signs:
                if not isinstance(item, dict):
                    continue
                sign = item.get("sign")
                text = item.get("text")
                if not isinstance(sign, str) or not isinstance(text, str):
                    continue
                entry: dict[str, str] = {
                    "date": row.forecast_date.isoformat(),
                    "text": text,
                }
                sign_meta = meta.get(sign)
                if isinstance(sign_meta, dict):
                    for key in ("headline", "central_idea", "action"):
                        value = sign_meta.get(key)
                        if isinstance(value, str) and value:
                            entry[key] = value
                history.setdefault(sign, []).append(entry)
        return history


def _fallback_snapshot(base: DailyHoroscopeSnapshot) -> DailyHoroscopeSnapshot:
    return DailyHoroscopeSnapshot(
        forecast_date=base.forecast_date,
        sky_digest=base.sky_digest,
        theme=base.theme,
        signs=base.signs,
        sky_version=base.sky_version,
        methodology_version=DAILY_AI_FALLBACK_METHOD_VERSION,
    )


def _is_current(snapshot: DailyHoroscopeSnapshot, *, ai_enabled: bool) -> bool:
    if snapshot.sky_version != DAILY_SKY_VERSION:
        return False
    if not ai_enabled:
        return snapshot.methodology_version == DAILY_EDITORIAL_METHOD_VERSION
    return snapshot.methodology_version in {
        DAILY_AI_METHOD_VERSION,
        DAILY_AI_FALLBACK_METHOD_VERSION,
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
