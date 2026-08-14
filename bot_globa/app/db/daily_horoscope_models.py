"""Persistence for default-on daily-horoscope delivery settings."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, String, func
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
    mode: Mapped[str] = mapped_column(String(16), default="morning", server_default="morning")
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
