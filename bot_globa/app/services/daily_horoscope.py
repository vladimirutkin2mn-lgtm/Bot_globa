"""Durable default-on and lease-based delivery for the common daily digest."""

from datetime import UTC, datetime, time, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import Date, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.daily_horoscope_models import DailyHoroscopeFeedback, DailyHoroscopePreference
from app.db.models import User
from app.domain.daily_horoscope import (
    DEFAULT_DAILY_HOROSCOPE_TIMEZONE,
    DailyHoroscopeClaim,
    DailyHoroscopeFeedbackAnswer,
    DailyHoroscopeFeedbackClaim,
    DailyHoroscopeMode,
    DailyHoroscopePreferenceView,
    timezone_for_moscow_time_difference,
)
from app.services.onboarding import CURRENT_CONSENT_VERSION

_DEFAULT_VIEW = DailyHoroscopePreferenceView(
    DailyHoroscopeMode.MORNING,
    DEFAULT_DAILY_HOROSCOPE_TIMEZONE,
    None,
)

_DELIVERY_TIMES = {
    DailyHoroscopeMode.MORNING: time(8, 0),
    DailyHoroscopeMode.EVENING: time(20, 0),
}
_FEEDBACK_TIME = time(20, 30)


class DailyHoroscopePreferenceService:
    """Store each user's local 08:00 schedule and lease every due delivery once."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def configure(
        self,
        user_id: UUID,
        mode: DailyHoroscopeMode,
        *,
        timezone: str | None = None,
        now: datetime | None = None,
    ) -> DailyHoroscopePreferenceView:
        current = _utc(now)
        if timezone is not None:
            ZoneInfo(timezone)
        async with self._sessions.begin() as session:
            preference = await _locked_preference(session, user_id, current)
            preference.mode = mode.value
            if timezone is not None:
                preference.timezone = timezone
            preference.next_delivery_at = _next_delivery(
                mode,
                current,
                preference.timezone,
            )
            preference.claim_id = None
            preference.lease_until = None
            await session.flush()
            return _view(preference)

    async def ensure_default(self, user_id: UUID, *, now: datetime | None = None) -> None:
        """Provision the default morning schedule when a Telegram account first appears.

        This is the only write on the default path, and it is deliberately not folded into
        `current`: reading the settings screen must not lock the user row or fail when the
        account is being deleted underneath it.
        """

        current = _utc(now)
        async with self._sessions.begin() as session:
            await _locked_preference(session, user_id, current)
            await session.flush()

    async def current(self, user_id: UUID) -> DailyHoroscopePreferenceView:
        """Report the saved settings without writing, locking or requiring an active user."""

        async with self._sessions() as session:
            preference = await session.get(DailyHoroscopePreference, user_id)
            return _DEFAULT_VIEW if preference is None else _view(preference)

    async def set_moscow_time_difference(
        self,
        user_id: UUID,
        difference: int,
        *,
        now: datetime | None = None,
    ) -> DailyHoroscopePreferenceView:
        """Keep the saved delivery mode while moving 08:00 to a new fixed local clock."""

        timezone = timezone_for_moscow_time_difference(difference)
        current = _utc(now)
        async with self._sessions.begin() as session:
            preference = await _locked_preference(session, user_id, current)
            preference.timezone = timezone
            mode = DailyHoroscopeMode(preference.mode)
            preference.next_delivery_at = _next_delivery(mode, current, timezone)
            preference.claim_id = None
            preference.lease_until = None
            await session.flush()
            return _view(preference)

    async def claim_due(
        self,
        *,
        now: datetime | None = None,
        lease_seconds: int = 60,
    ) -> DailyHoroscopeClaim | None:
        """Lease one due row without consuming its delivery day.

        Snapshot calculation, rendering and other local preparation happen after this
        lease. If they fail, releasing the claim leaves the row due for another attempt.
        The irreversible day reservation is deliberately deferred to `reserve_send`.
        """

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
                        or_(
                            DailyHoroscopePreference.last_delivered_on.is_(None),
                            DailyHoroscopePreference.last_delivered_on
                            < cast(
                                func.timezone(DailyHoroscopePreference.timezone, current),
                                Date,
                            ),
                        ),
                        User.telegram_user_id.is_not(None),
                        User.privacy_status != "deleted",
                        User.consent_version == CURRENT_CONSENT_VERSION,
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
            mode = DailyHoroscopeMode(preference.mode)
            local_date = current.astimezone(ZoneInfo(preference.timezone)).date()
            preference.claim_id = claim_id
            preference.lease_until = current + timedelta(seconds=lease_seconds)
            await session.flush()
            return DailyHoroscopeClaim(
                claim_id=claim_id,
                user_id=preference.user_id,
                telegram_user_id=int(telegram_user_id),
                delivery_date=local_date,
                mode=mode,
            )

    async def reserve_send(
        self,
        claim: DailyHoroscopeClaim,
        *,
        now: datetime | None = None,
    ) -> bool:
        """Reserve the local day immediately before the first Telegram send attempt.

        Telegram has no idempotency key for sendPhoto/sendMessage. Reserving here keeps
        the at-most-once guarantee for the ambiguous crash window after Telegram accepts a
        request, while failures during snapshot calculation or rendering remain retryable.
        """

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
            if mode is not claim.mode:
                return False
            local_date = current.astimezone(ZoneInfo(preference.timezone)).date()
            if local_date != claim.delivery_date:
                return False
            if (
                preference.last_delivered_on is not None
                and preference.last_delivered_on >= claim.delivery_date
            ):
                return False
            preference.last_delivered_on = claim.delivery_date
            preference.next_delivery_at = _next_delivery(mode, current, preference.timezone)
            await session.flush()
            return True

    async def complete(
        self,
        claim: DailyHoroscopeClaim,
        *,
        now: datetime | None = None,
    ) -> bool:
        """Acknowledge a reserved send and clear its lease."""

        _utc(now)
        async with self._sessions.begin() as session:
            preference = await session.get(
                DailyHoroscopePreference,
                claim.user_id,
                with_for_update=True,
            )
            if preference is None or preference.claim_id != claim.claim_id:
                return False
            if preference.last_delivered_on != claim.delivery_date:
                return False
            preference.claim_id = None
            preference.lease_until = None
            if claim.mode is DailyHoroscopeMode.MORNING:
                feedback = await session.get(
                    DailyHoroscopeFeedback,
                    (claim.user_id, claim.delivery_date),
                )
                if feedback is None:
                    session.add(
                        DailyHoroscopeFeedback(
                            user_id=claim.user_id,
                            forecast_date=claim.delivery_date,
                            due_at=_feedback_due_at(claim.delivery_date, preference.timezone),
                        )
                    )
            return True

    async def claim_feedback_due(
        self,
        *,
        now: datetime | None = None,
        lease_seconds: int = 60,
    ) -> DailyHoroscopeFeedbackClaim | None:
        """Lease one evening usefulness prompt that has not been sent yet."""

        if lease_seconds < 1:
            raise ValueError("daily horoscope feedback lease must be positive")
        current = _utc(now)
        async with self._sessions.begin() as session:
            row = (
                await session.execute(
                    select(DailyHoroscopeFeedback, User.telegram_user_id)
                    .join(User, User.id == DailyHoroscopeFeedback.user_id)
                    .where(
                        DailyHoroscopeFeedback.due_at <= current,
                        DailyHoroscopeFeedback.prompted_at.is_(None),
                        or_(
                            DailyHoroscopeFeedback.prompt_lease_until.is_(None),
                            DailyHoroscopeFeedback.prompt_lease_until <= current,
                        ),
                        User.telegram_user_id.is_not(None),
                        User.privacy_status != "deleted",
                        User.consent_version == CURRENT_CONSENT_VERSION,
                    )
                    .order_by(DailyHoroscopeFeedback.due_at)
                    .with_for_update(of=DailyHoroscopeFeedback, skip_locked=True)
                    .limit(1)
                )
            ).one_or_none()
            if row is None:
                return None
            feedback, telegram_user_id = row
            claim_id = uuid4()
            feedback.prompt_claim_id = claim_id
            feedback.prompt_lease_until = current + timedelta(seconds=lease_seconds)
            await session.flush()
            return DailyHoroscopeFeedbackClaim(
                claim_id=claim_id,
                user_id=feedback.user_id,
                telegram_user_id=int(telegram_user_id),
                forecast_date=feedback.forecast_date,
            )

    async def reserve_feedback_prompt(
        self,
        claim: DailyHoroscopeFeedbackClaim,
        *,
        now: datetime | None = None,
    ) -> bool:
        """Reserve the prompt before Telegram I/O so a crash cannot duplicate it."""

        current = _utc(now)
        async with self._sessions.begin() as session:
            feedback = await session.get(
                DailyHoroscopeFeedback,
                (claim.user_id, claim.forecast_date),
                with_for_update=True,
            )
            if feedback is None or feedback.prompt_claim_id != claim.claim_id:
                return False
            if feedback.prompted_at is not None:
                return False
            feedback.prompted_at = current
            await session.flush()
            return True

    async def complete_feedback_prompt(
        self,
        claim: DailyHoroscopeFeedbackClaim,
        *,
        now: datetime | None = None,
    ) -> bool:
        """Acknowledge a reserved feedback prompt and clear its lease."""

        _utc(now)
        async with self._sessions.begin() as session:
            feedback = await session.get(
                DailyHoroscopeFeedback,
                (claim.user_id, claim.forecast_date),
                with_for_update=True,
            )
            if (
                feedback is None
                or feedback.prompt_claim_id != claim.claim_id
                or feedback.prompted_at is None
            ):
                return False
            feedback.prompt_claim_id = None
            feedback.prompt_lease_until = None
            return True

    async def release_feedback_prompt(
        self,
        claim: DailyHoroscopeFeedbackClaim,
        *,
        now: datetime | None = None,
    ) -> bool:
        """Drop a feedback lease without making an unsent prompt look delivered."""

        _utc(now)
        async with self._sessions.begin() as session:
            feedback = await session.get(
                DailyHoroscopeFeedback,
                (claim.user_id, claim.forecast_date),
                with_for_update=True,
            )
            if feedback is None or feedback.prompt_claim_id != claim.claim_id:
                return False
            feedback.prompt_claim_id = None
            feedback.prompt_lease_until = None
            return True

    async def submit_feedback(
        self,
        user_id: UUID,
        forecast_date: date,
        answer: DailyHoroscopeFeedbackAnswer,
        *,
        now: datetime | None = None,
    ) -> bool:
        """Persist the first one-tap answer for a prompt that was actually sent."""

        current = _utc(now)
        async with self._sessions.begin() as session:
            feedback = await session.get(
                DailyHoroscopeFeedback,
                (user_id, forecast_date),
                with_for_update=True,
            )
            if feedback is None or feedback.prompted_at is None or feedback.answer is not None:
                return False
            feedback.answer = answer.value
            feedback.answered_at = current
            return True

    async def release(
        self,
        claim: DailyHoroscopeClaim,
        *,
        now: datetime | None = None,
    ) -> bool:
        """Drop a lease without changing delivery state.

        Before `reserve_send`, this makes a preparation failure retryable because the row
        stays due and the day stays unreserved. After `reserve_send`, the day remains
        reserved on purpose because a Telegram failure may be ambiguous.
        """

        _utc(now)
        async with self._sessions.begin() as session:
            preference = await session.get(
                DailyHoroscopePreference,
                claim.user_id,
                with_for_update=True,
            )
            if preference is None or preference.claim_id != claim.claim_id:
                return False
            preference.claim_id = None
            preference.lease_until = None
            return True


def _view(preference: DailyHoroscopePreference) -> DailyHoroscopePreferenceView:
    return DailyHoroscopePreferenceView(
        mode=DailyHoroscopeMode(preference.mode),
        timezone=preference.timezone,
        next_delivery_at=preference.next_delivery_at,
    )


async def _locked_preference(
    session: AsyncSession,
    user_id: UUID,
    now: datetime,
) -> DailyHoroscopePreference:
    user = await session.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None or user.privacy_status == "deleted" or user.telegram_user_id is None:
        raise LookupError("active Telegram user is required")
    preference = await session.get(
        DailyHoroscopePreference,
        user_id,
        with_for_update=True,
    )
    if preference is None:
        preference = DailyHoroscopePreference(
            user_id=user_id,
            mode=DailyHoroscopeMode.MORNING.value,
            timezone=DEFAULT_DAILY_HOROSCOPE_TIMEZONE,
            next_delivery_at=_next_delivery(
                DailyHoroscopeMode.MORNING,
                now,
                DEFAULT_DAILY_HOROSCOPE_TIMEZONE,
            ),
        )
        session.add(preference)
    return preference


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


def _feedback_due_at(forecast_date: date, timezone: str) -> datetime:
    zone = ZoneInfo(timezone)
    return datetime.combine(forecast_date, _FEEDBACK_TIME, tzinfo=zone).astimezone(UTC)
