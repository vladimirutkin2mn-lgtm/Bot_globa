"""Explicit-consent contracts for encrypted birth profile reuse."""

import math
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

CURRENT_BIRTH_PROFILE_CONSENT_VERSION = "birth-profile-consent-v1"
CURRENT_BIRTH_PROFILE_FORMAT_VERSION = 1
CURRENT_BIRTH_PROFILE_VERSION = "birth-profile-v1"
CURRENT_BIRTH_PROFILE_NORMALIZATION_VERSION = "birth-profile-normalizer-v1"


class BirthProfileConsentStatus(StrEnum):
    GRANTED = "granted"
    REVOKED = "revoked"


class BirthProfileStatus(StrEnum):
    ACTIVE = "active"
    DELETED = "deleted"


@dataclass(frozen=True, slots=True)
class BirthProfileInput:
    birth_date: date
    birth_place: str
    timezone: str
    latitude: float
    longitude: float
    utc_offset_minutes: int
    birth_time: time | None = None

    def __post_init__(self) -> None:
        place = unicodedata.normalize("NFKC", " ".join(self.birth_place.split()))
        timezone_name = self.timezone.strip()
        if not place or len(place) > 200:
            raise ValueError("birth place must contain between 1 and 200 characters")
        if not timezone_name or len(timezone_name) > 64:
            raise ValueError("birth timezone must contain between 1 and 64 characters")
        if self.birth_date > date.today():
            raise ValueError("birth date cannot be in the future")
        if self.birth_time is not None and self.birth_time.tzinfo is not None:
            raise ValueError("birth time must be local and timezone-naive")
        if isinstance(self.latitude, bool) or not math.isfinite(self.latitude):
            raise ValueError("birth latitude must be finite")
        if isinstance(self.longitude, bool) or not math.isfinite(self.longitude):
            raise ValueError("birth longitude must be finite")
        if not -90.0 <= self.latitude <= 90.0:
            raise ValueError("birth latitude must be between -90 and 90")
        if not -180.0 <= self.longitude <= 180.0:
            raise ValueError("birth longitude must be between -180 and 180")
        if isinstance(self.utc_offset_minutes, bool) or not isinstance(
            self.utc_offset_minutes, int
        ):
            raise ValueError("birth UTC offset must be an integer number of minutes")
        if not -840 <= self.utc_offset_minutes <= 840:
            raise ValueError("birth UTC offset must be between -840 and 840 minutes")
        try:
            zone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("birth timezone must be a valid IANA timezone") from exc
        valid_offsets = self._valid_offsets(zone)
        if self.utc_offset_minutes not in valid_offsets:
            raise ValueError("birth UTC offset is inconsistent with local date and timezone")
        object.__setattr__(self, "birth_place", place)
        object.__setattr__(self, "timezone", zone.key)
        object.__setattr__(self, "latitude", round(float(self.latitude), 6))
        object.__setattr__(self, "longitude", round(float(self.longitude), 6))

    @property
    def time_known(self) -> bool:
        return self.birth_time is not None

    def local_calculation_datetime(self) -> datetime:
        """Return exact local time or the documented local-noon date-only assumption."""
        return datetime.combine(
            self.birth_date,
            self.birth_time if self.birth_time is not None else time(12, 0),
        )

    def utc_calculation_datetime(self) -> datetime:
        local = self.local_calculation_datetime()
        return (local - self._offset_delta()).replace(tzinfo=UTC)

    def encrypted_payload(self) -> dict[str, str | int | float | None]:
        return {
            "birth_date": self.birth_date.isoformat(),
            "birth_time": None if self.birth_time is None else self.birth_time.isoformat(),
            "birth_place": self.birth_place,
            "timezone": self.timezone,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "utc_offset_minutes": self.utc_offset_minutes,
        }

    @classmethod
    def from_encrypted_payload(cls, payload: object) -> "BirthProfileInput":
        if not isinstance(payload, dict):
            raise ValueError("invalid decrypted birth profile shape")
        expected = {
            "birth_date",
            "birth_time",
            "birth_place",
            "timezone",
            "latitude",
            "longitude",
            "utc_offset_minutes",
        }
        if set(payload) != expected:
            raise ValueError("invalid decrypted birth profile fields")
        birth_date_value = payload["birth_date"]
        birth_time_value = payload["birth_time"]
        birth_place = payload["birth_place"]
        timezone_name = payload["timezone"]
        latitude = payload["latitude"]
        longitude = payload["longitude"]
        utc_offset_minutes = payload["utc_offset_minutes"]
        if not isinstance(birth_date_value, str):
            raise ValueError("invalid decrypted birth date")
        if birth_time_value is not None and not isinstance(birth_time_value, str):
            raise ValueError("invalid decrypted birth time")
        if not isinstance(birth_place, str) or not isinstance(timezone_name, str):
            raise ValueError("invalid decrypted birth location")
        if isinstance(latitude, bool) or not isinstance(latitude, int | float):
            raise ValueError("invalid decrypted birth latitude")
        if isinstance(longitude, bool) or not isinstance(longitude, int | float):
            raise ValueError("invalid decrypted birth longitude")
        if isinstance(utc_offset_minutes, bool) or not isinstance(utc_offset_minutes, int):
            raise ValueError("invalid decrypted birth UTC offset")
        return cls(
            birth_date=date.fromisoformat(birth_date_value),
            birth_time=(None if birth_time_value is None else time.fromisoformat(birth_time_value)),
            birth_place=birth_place,
            timezone=timezone_name,
            latitude=float(latitude),
            longitude=float(longitude),
            utc_offset_minutes=utc_offset_minutes,
        )

    def _valid_offsets(self, zone: ZoneInfo) -> set[int]:
        local = self.local_calculation_datetime()
        valid: set[int] = set()
        for fold in (0, 1):
            aware = local.replace(tzinfo=zone, fold=fold)
            utc = aware.astimezone(UTC)
            if utc.astimezone(zone).replace(tzinfo=None) != local:
                continue
            offset = aware.utcoffset()
            if offset is not None:
                valid.add(round(offset.total_seconds() / 60))
        if not valid:
            raise ValueError("birth local time does not exist in the selected timezone")
        return valid

    def _offset_delta(self) -> timedelta:
        return timedelta(minutes=self.utc_offset_minutes)


@dataclass(frozen=True, slots=True)
class BirthProfileConsentView:
    status: BirthProfileConsentStatus
    consent_version: str
    accepted_at: datetime | None
    revoked_at: datetime | None


@dataclass(frozen=True, slots=True)
class BirthProfileView:
    profile: BirthProfileInput
    profile_version: str
    created_at: datetime
    updated_at: datetime
