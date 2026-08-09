"""Turn a free-text birth place into the exact inputs the astrology engine needs.

The calculation engine needs coordinates, an IANA timezone and the UTC offset that was
in force at the moment of birth. The offset is derived here from the timezone and the
local birth datetime rather than taken from the provider, so a historical birth uses the
rules of its own era.
"""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.domain.birth_profile import BirthProfileInput
from app.providers.geocoding.base import (
    MAX_PLACE_CANDIDATES,
    MAX_PLACE_QUERY_LENGTH,
    GeocodedPlace,
    GeocodingClient,
)

MIN_PLACE_QUERY_LENGTH = 2


class InvalidBirthPlaceQueryError(ValueError):
    """The query is unusable; the message never repeats what the user typed."""


class UnresolvableBirthPlaceError(ValueError):
    """A resolved place cannot produce a valid profile for this date and time."""


class BirthPlaceLookupService:
    """Search for candidate places and assemble a validated birth profile."""

    def __init__(
        self,
        geocoder: GeocodingClient,
        *,
        max_candidates: int = MAX_PLACE_CANDIDATES,
    ) -> None:
        self._geocoder = geocoder
        self._max_candidates = max_candidates

    async def search(self, query: str) -> tuple[GeocodedPlace, ...]:
        cleaned = " ".join(query.split())
        if not MIN_PLACE_QUERY_LENGTH <= len(cleaned) <= MAX_PLACE_QUERY_LENGTH:
            raise InvalidBirthPlaceQueryError("birth place query length is out of range")
        return await self._geocoder.search(cleaned, limit=self._max_candidates)

    @staticmethod
    def build_profile(
        place: GeocodedPlace,
        birth_date: date,
        birth_time: time | None,
    ) -> BirthProfileInput:
        """Assemble the profile, deriving the era-correct UTC offset from the timezone."""
        try:
            zone = ZoneInfo(place.timezone)
        except ZoneInfoNotFoundError as error:
            raise UnresolvableBirthPlaceError("resolved timezone is unknown") from error
        local = datetime.combine(birth_date, birth_time if birth_time is not None else time(12, 0))
        offset = local.replace(tzinfo=zone).utcoffset()
        if offset is None:
            raise UnresolvableBirthPlaceError("resolved timezone has no offset for this moment")
        try:
            return BirthProfileInput(
                birth_date=birth_date,
                birth_time=birth_time,
                birth_place=place.label,
                timezone=place.timezone,
                latitude=place.latitude,
                longitude=place.longitude,
                utc_offset_minutes=round(offset.total_seconds() / 60),
            )
        except ValueError as error:
            # A local time inside a DST gap does not exist; the caller asks for another time.
            raise UnresolvableBirthPlaceError("birth moment is invalid for this place") from error
