"""Durable opt-in and lease-based delivery for the common daily digest."""

from datetime import UTC, datetime, time, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.daily_horoscope_models import DailyHoroscopePreference
from app.db.models import User
from app.domain.daily_horoscope import (
    DEFAULT_DAILY_HOROSCOPE_TIMEZONE,
    DailyHoroscopeClaim,
    DailyHoroscopeMode,
    DailyHoroscopePreferenceView,
)

_DELIVERY_TIMES = {
    DailyHoroscopeMode.MORNING: time(8, 0),
    DailyHoroscopeMode.EVENING: time(20, 0),
}


class DailyHoroscopePreferenceService:
    """Store a voluntary schedule and let one worker lease each due delivery."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def configure(
        self,
        user_id: UUID,
        mode: DailyHoroscopeMode,
        *,
        now: datetime | None = None,
    ) -> DailyHoroscopePreferenceView:
        current = _utc(now)
        async with self._sessions.begin() as session:
            user = await session.scalar(select(User).where(User.id == user_id).with_for_update())
            if user is None or user.privacy_status == "deleted" or user.telegram_user_id is None:
                raise LookupError("active Telegram user is required")
            preference = await session.get(
                DailyHoroscopePreference,
                user_id,
                with_for_update=True,
            )
            if preference is None:
                preference = DailyHoroscopePreference(user_id=user_id)
                session.add(preference)
            preference.mode = mode.value
            preference.timezone = DEFAULT_DAILY_HOROSCOPE_TIMEZONE
            preference.next_delivery_at = _next_delivery(
                mode,
                current,
                DEFAULT_DAILY_HOROSCOPE_TIMEZONE,
            )
            preference.claim_id = None
            preference.lease_until = None
            await session.flush()
            return _view(preference)

    async def current(self, user_id: UUID) -> DailyHoroscopePreferenceView:
        async with self._sessions() as session:
            preference = await session.get(DailyHoroscopePreference, user_id)
            if preference is None:
                return DailyHoroscopePreferenceView(
                    DailyHoroscopeMode.ON_REQUEST,
                    DEFAULT_DAILY_HOROSCOPE_TIMEZONE,
                    None,
                )
            return _view(preference)

    async def claim_due(
        self,
        *,
        now: datetime | None = None,
        lease_seconds: int = 60,
    ) -> DailyHoroscopeClaim | None:
        if lease_seconds < 1:
            raise ValueError("daily horoscope lease must be positive")
        current = _utc(now)
        async with self._sessions.begin() as session:
            row = (
                await session.execute(
                    select(DailyHoroscopePreference, User.telegram_user_id)
                    .join(User, User.id == DailyHoroscopePreference.user_id)
                    .where(
                        DailyHoroscopePreference.mode.in_(
                            (DailyHoroscopeMode.MORNING.value, DailyHoroscopeMode.EVENING.value)
                        ),
                        DailyHoroscopePreference.next_delivery_at <= current,
                        or_(
                            DailyHoroscopePreference.lease_until.is_(None),
                            DailyHoroscopePreference.lease_until <= current,
                        ),
                        User.telegram_user_id.is_not(None),
                        User.privacy_status != "deleted",
                    )
                    .order_by(DailyHoroscopePreference.next_delivery_at)
                    .with_for_update(of=DailyHoroscopePreference, skip_locked=True)
                    .limit(1)
                )
            ).one_or_none()
            if row is None:
                return None
            preference, telegram_user_id = row
            claim_id = uuid4()
            preference.claim_id = claim_id
            preference.lease_until = current + timedelta(seconds=lease_seconds)
            mode = DailyHoroscopeMode(preference.mode)
            local_date = current.astimezone(ZoneInfo(preference.timezone)).date()
            await session.flush()
            return DailyHoroscopeClaim(
                claim_id=claim_id,
                user_id=preference.user_id,
                telegram_user_id=int(telegram_user_id),
                delivery_date=local_date,
                mode=mode,
            )

    async def complete(
        self,
        claim: DailyHoroscopeClaim,
        *,
        now: datetime | None = None,
    ) -> bool:
        current = _utc(now)
        async with self._sessions.begin() as session:
            preference = await session.get(
                DailyHoroscopePreference,
                claim.user_id,
                with_for_update=True,
            )
            if preference is None or preference.claim_id != claim.claim_id:
                return False
            mode = DailyHoroscopeMode(preference.mode)
            preference.last_delivered_on = claim.delivery_date
            preference.next_delivery_at = _next_delivery(mode, current, preference.timezone)
            preference.claim_id = None
            preference.lease_until = None
            return True

    async def release(
        self,
        claim: DailyHoroscopeClaim,
        *,
        now: datetime | None = None,
    ) -> bool:
        current = _utc(now)
        async with self._sessions.begin() as session:
            preference = await session.get(
                DailyHoroscopePreference,
                claim.user_id,
                with_for_update=True,
            )
            if preference is None or preference.claim_id != claim.claim_id:
                return False
            preference.next_delivery_at = current + timedelta(minutes=5)
            preference.claim_id = None
            preference.lease_until = None
            return True


def _view(preference: DailyHoroscopePreference) -> DailyHoroscopePreferenceView:
    return DailyHoroscopePreferenceView(
        mode=DailyHoroscopeMode(preference.mode),
        timezone=preference.timezone,
        next_delivery_at=preference.next_delivery_at,
    )


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(UTC)
    if current.tzinfo is None:
        raise ValueError("daily horoscope time must be timezone-aware")
    return current.astimezone(UTC)


def _next_delivery(mode: DailyHoroscopeMode, now: datetime, timezone: str) -> datetime | None:
    clock = _DELIVERY_TIMES.get(mode)
    if clock is None:
        return None
    zone = ZoneInfo(timezone)
    local_now = now.astimezone(zone)
    candidate = datetime.combine(local_now.date(), clock, tzinfo=zone)
    if candidate <= local_now:
        candidate += timedelta(days=1)
    return candidate.astimezone(UTC)
