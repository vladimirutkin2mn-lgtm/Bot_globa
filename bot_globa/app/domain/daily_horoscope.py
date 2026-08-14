"""Contracts for the default-on, non-personal daily horoscope digest."""

import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

DEFAULT_DAILY_HOROSCOPE_TIMEZONE = "Europe/Moscow"
MOSCOW_UTC_OFFSET_HOURS = 3
MIN_MOSCOW_TIME_DIFFERENCE_HOURS = -15
MAX_MOSCOW_TIME_DIFFERENCE_HOURS = 11

_ETC_GMT_TIMEZONE = re.compile(r"Etc/GMT(?P<sign>[+-])(?P<hours>\d{1,2})")


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


def daily_horoscope_enabled(mode: DailyHoroscopeMode) -> bool:
    """Treat the two historical scheduled modes as enabled during migration."""

    return mode in {DailyHoroscopeMode.MORNING, DailyHoroscopeMode.EVENING}


def parse_moscow_time_difference(value: str) -> int:
    """Parse a whole-hour difference entered relative to Moscow time."""

    normalized = value.strip().replace("−", "-").replace("–", "-").replace("—", "-")
    if re.fullmatch(r"[+-]?\d{1,2}", normalized) is None:
        raise ValueError("Moscow time difference must be a whole number of hours")
    difference = int(normalized)
    if not MIN_MOSCOW_TIME_DIFFERENCE_HOURS <= difference <= MAX_MOSCOW_TIME_DIFFERENCE_HOURS:
        raise ValueError("Moscow time difference is outside supported world time zones")
    return difference


def timezone_for_moscow_time_difference(difference: int) -> str:
    """Return a fixed IANA zone whose clock is Moscow plus ``difference`` hours."""

    if not MIN_MOSCOW_TIME_DIFFERENCE_HOURS <= difference <= MAX_MOSCOW_TIME_DIFFERENCE_HOURS:
        raise ValueError("Moscow time difference is outside supported world time zones")
    utc_offset = MOSCOW_UTC_OFFSET_HOURS + difference
    if utc_offset == 0:
        return "Etc/GMT"
    # IANA's Etc/GMT names use the POSIX sign convention: ``Etc/GMT-5`` is UTC+5.
    sign = "-" if utc_offset > 0 else "+"
    return f"Etc/GMT{sign}{abs(utc_offset)}"


def moscow_time_difference_for_timezone(timezone: str) -> int | None:
    """Recover the user-facing Moscow difference from a stored fixed IANA zone."""

    if timezone == DEFAULT_DAILY_HOROSCOPE_TIMEZONE:
        return 0
    if timezone == "Etc/GMT":
        return -MOSCOW_UTC_OFFSET_HOURS
    match = _ETC_GMT_TIMEZONE.fullmatch(timezone)
    if match is None:
        return None
    hours = int(match.group("hours"))
    utc_offset = hours if match.group("sign") == "-" else -hours
    difference = utc_offset - MOSCOW_UTC_OFFSET_HOURS
    if MIN_MOSCOW_TIME_DIFFERENCE_HOURS <= difference <= MAX_MOSCOW_TIME_DIFFERENCE_HOURS:
        return difference
    return None
