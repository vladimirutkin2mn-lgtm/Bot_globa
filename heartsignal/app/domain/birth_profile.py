"""Explicit-consent contracts for encrypted birth profile reuse."""

from dataclasses import dataclass
from datetime import date, datetime, time
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

CURRENT_BIRTH_PROFILE_CONSENT_VERSION = "birth-profile-consent-v1"
CURRENT_BIRTH_PROFILE_FORMAT_VERSION = 1
CURRENT_BIRTH_PROFILE_VERSION = "birth-profile-v1"


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
    birth_time: time | None = None

    def __post_init__(self) -> None:
        place = self.birth_place.strip()
        timezone = self.timezone.strip()
        if not place or len(place) > 200:
            raise ValueError("birth place must contain between 1 and 200 characters")
        if not timezone or len(timezone) > 64:
            raise ValueError("birth timezone must contain between 1 and 64 characters")
        if self.birth_date > date.today():
            raise ValueError("birth date cannot be in the future")
        try:
            ZoneInfo(timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("birth timezone must be a valid IANA timezone") from exc
        object.__setattr__(self, "birth_place", place)
        object.__setattr__(self, "timezone", timezone)

    def encrypted_payload(self) -> dict[str, str | None]:
        return {
            "birth_date": self.birth_date.isoformat(),
            "birth_time": None if self.birth_time is None else self.birth_time.isoformat(),
            "birth_place": self.birth_place,
            "timezone": self.timezone,
        }

    @classmethod
    def from_encrypted_payload(cls, payload: object) -> "BirthProfileInput":
        if not isinstance(payload, dict):
            raise ValueError("invalid decrypted birth profile shape")
        expected = {"birth_date", "birth_time", "birth_place", "timezone"}
        if set(payload) != expected:
            raise ValueError("invalid decrypted birth profile fields")
        birth_date = payload["birth_date"]
        birth_time = payload["birth_time"]
        birth_place = payload["birth_place"]
        timezone = payload["timezone"]
        if not isinstance(birth_date, str):
            raise ValueError("invalid decrypted birth date")
        if birth_time is not None and not isinstance(birth_time, str):
            raise ValueError("invalid decrypted birth time")
        if not isinstance(birth_place, str) or not isinstance(timezone, str):
            raise ValueError("invalid decrypted birth location")
        return cls(
            birth_date=date.fromisoformat(birth_date),
            birth_time=None if birth_time is None else time.fromisoformat(birth_time),
            birth_place=birth_place,
            timezone=timezone,
        )


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
