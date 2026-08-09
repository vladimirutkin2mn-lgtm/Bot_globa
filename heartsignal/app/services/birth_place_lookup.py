"""Turn a free-text birth place into the exact inputs the astrology engine needs.

The calculation engine needs coordinates, an IANA timezone and the UTC offset that was
in force at the moment of birth. The offset is derived here from the timezone and the
local birth datetime rather than taken from the provider, so a historical birth uses the
rules of its own era.
"""

from datetime import UTC, date, datetime, time
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


class AmbiguousBirthTimeError(ValueError):
    """The local time occurs twice because the clocks went back.

    Both offsets are one real hour apart, which moves the ascendant and the houses, so
    the caller must ask rather than let the library pick `fold=0`.
    """

    def __init__(self, offsets: tuple[int, ...]) -> None:
        super().__init__("birth time is ambiguous for this place")
        self.offsets = offsets


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
    def candidate_offsets(
        place: GeocodedPlace,
        birth_date: date,
        birth_time: time | None,
    ) -> tuple[int, ...]:
        """Every UTC offset under which this local moment actually existed.

        Empty when the clocks jumped forward over it, two when they went back and the
        hour repeated, otherwise one.
        """
        try:
            zone = ZoneInfo(place.timezone)
        except ZoneInfoNotFoundError as error:
            raise UnresolvableBirthPlaceError("resolved timezone is unknown") from error
        local = _local_moment(birth_date, birth_time)
        offsets: set[int] = set()
        for fold in (0, 1):
            aware = local.replace(tzinfo=zone, fold=fold)
            if aware.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != local:
                continue
            offset = aware.utcoffset()
            if offset is not None:
                offsets.add(round(offset.total_seconds() / 60))
        return tuple(sorted(offsets))

    @classmethod
    def build_profile(
        cls,
        place: GeocodedPlace,
        birth_date: date,
        birth_time: time | None,
        utc_offset_minutes: int | None = None,
    ) -> BirthProfileInput:
        """Assemble the profile, deriving the era-correct UTC offset from the timezone.

        `utc_offset_minutes` resolves a repeated hour after the user has chosen; without
        it an ambiguous moment raises rather than silently taking the first offset.
        """
        if birth_date > datetime.now(UTC).date():
            raise UnresolvableBirthPlaceError("birth date cannot be in the future")
        offsets = cls.candidate_offsets(place, birth_date, birth_time)
        if not offsets:
            raise UnresolvableBirthPlaceError("birth moment does not exist for this place")
        if utc_offset_minutes is None:
            if len(offsets) > 1:
                raise AmbiguousBirthTimeError(offsets)
            utc_offset_minutes = offsets[0]
        elif utc_offset_minutes not in offsets:
            raise UnresolvableBirthPlaceError("offset does not match this place and moment")
        try:
            return BirthProfileInput(
                birth_date=birth_date,
                birth_time=birth_time,
                birth_place=place.label,
                timezone=place.timezone,
                latitude=place.latitude,
                longitude=place.longitude,
                utc_offset_minutes=utc_offset_minutes,
            )
        except ValueError as error:
            raise UnresolvableBirthPlaceError("birth moment is invalid for this place") from error


def _local_moment(birth_date: date, birth_time: time | None) -> datetime:
    """An unknown time uses the documented local-noon assumption."""
    return datetime.combine(birth_date, birth_time if birth_time is not None else time(12, 0))
