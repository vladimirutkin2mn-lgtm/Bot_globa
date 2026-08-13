"""Contracts for the opt-in, non-personal daily horoscope digest."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

DEFAULT_DAILY_HOROSCOPE_TIMEZONE = "Europe/Moscow"


class DailyHoroscopeMode(StrEnum):
    MORNING = "morning"
    EVENING = "evening"
    ON_REQUEST = "on_request"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class DailyHoroscopePreferenceView:
    mode: DailyHoroscopeMode
    timezone: str
    next_delivery_at: datetime | None


@dataclass(frozen=True, slots=True)
class DailyHoroscopeClaim:
    claim_id: UUID
    user_id: UUID
    telegram_user_id: int
    delivery_date: date
    mode: DailyHoroscopeMode
