"""Persistence for daily-horoscope delivery settings and shared content snapshots."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, Date, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DailyHoroscopePreference(Base):
    __tablename__ = "daily_horoscope_preferences"
    __table_args__ = (
        CheckConstraint(
            "mode IN ('morning','evening','on_request','disabled')",
            name="ck_daily_horoscope_preferences_mode",
        ),
        CheckConstraint(
            "(mode IN ('morning','evening') AND next_delivery_at IS NOT NULL) OR "
            "(mode IN ('on_request','disabled') AND next_delivery_at IS NULL)",
            name="ck_daily_horoscope_preferences_schedule",
        ),
        CheckConstraint(
            "(claim_id IS NULL AND lease_until IS NULL) OR "
            "(claim_id IS NOT NULL AND lease_until IS NOT NULL)",
            name="ck_daily_horoscope_preferences_claim",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # No default: `ck_daily_horoscope_preferences_schedule` ties the mode to whether
    # `next_delivery_at` is set, and that column cannot have a default. Any default here
    # would therefore guarantee a check violation for the insert that relies on it, so
    # every writer states both columns explicitly.
    mode: Mapped[str] = mapped_column(String(16))
    timezone: Mapped[str] = mapped_column(
        String(64), default="Europe/Moscow", server_default="Europe/Moscow"
    )
    next_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    claim_id: Mapped[UUID | None] = mapped_column(index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_delivered_on: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DailyHoroscopeSnapshotRow(Base):
    """Immutable shared digest content for a civil date and methodology version."""

    __tablename__ = "daily_horoscope_snapshots"

    forecast_date: Mapped[date] = mapped_column(Date, primary_key=True)
    sky_version: Mapped[str] = mapped_column(String(64), nullable=False)
    methodology_version: Mapped[str] = mapped_column(String(64), nullable=False)
    sky_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DailyHoroscopeFeedback(Base):
    """One evening usefulness response for one delivered daily horoscope."""

    __tablename__ = "daily_horoscope_feedback"
    __table_args__ = (
        CheckConstraint(
            "answer IS NULL OR answer IN ('useful','not_useful')",
            name="ck_daily_horoscope_feedback_answer",
        ),
        CheckConstraint(
            "(answer IS NULL AND answered_at IS NULL) OR "
            "(answer IS NOT NULL AND answered_at IS NOT NULL)",
            name="ck_daily_horoscope_feedback_answered",
        ),
        CheckConstraint(
            "(prompt_claim_id IS NULL AND prompt_lease_until IS NULL) OR "
            "(prompt_claim_id IS NOT NULL AND prompt_lease_until IS NOT NULL)",
            name="ck_daily_horoscope_feedback_claim",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    forecast_date: Mapped[date] = mapped_column(Date, primary_key=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    prompt_claim_id: Mapped[UUID | None] = mapped_column(index=True)
    prompt_lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    prompted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answer: Mapped[str | None] = mapped_column(String(16))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
