"""Assembling a birth profile from a resolved place.

The UTC offset must come from the timezone rules that were in force at the moment of
birth, not from today's rules — the calculated chart depends on it.
"""

from datetime import UTC, date, datetime, time

import pytest

from app.providers.geocoding.base import GeocodedPlace
from app.providers.geocoding.stub import StubGeocodingClient
from app.services.birth_place_lookup import (
    AmbiguousBirthTimeError,
    BirthPlaceLookupService,
    InvalidBirthPlaceQueryError,
    UnresolvableBirthPlaceError,
)

MOSCOW = GeocodedPlace("Москва, Россия", 55.755864, 37.617698, "Europe/Moscow")
PARIS = GeocodedPlace("Париж, Франция", 48.856613, 2.352222, "Europe/Paris")


def _service() -> BirthPlaceLookupService:
    return BirthPlaceLookupService(StubGeocodingClient())


def test_offset_follows_the_rules_of_the_birth_era_not_today() -> None:
    service = _service()

    summer_1990 = service.build_profile(MOSCOW, date(1990, 7, 12), time(14, 30))
    winter_1985 = service.build_profile(MOSCOW, date(1985, 1, 5), time(3, 0))
    after_2014 = service.build_profile(MOSCOW, date(2020, 7, 12), time(14, 30))

    assert summer_1990.utc_offset_minutes == 240
    assert winter_1985.utc_offset_minutes == 180
    assert after_2014.utc_offset_minutes == 180


def test_an_unknown_time_uses_the_documented_local_noon_assumption() -> None:
    profile = _service().build_profile(PARIS, date(1991, 4, 17), None)

    assert not profile.time_known
    assert profile.local_calculation_datetime().hour == 12


def test_a_local_time_inside_a_dst_gap_is_refused_rather_than_guessed() -> None:
    # 1981-04-01 00:00 does not exist in Moscow: Soviet summer time skipped that hour.
    with pytest.raises(UnresolvableBirthPlaceError):
        _service().build_profile(MOSCOW, date(1981, 4, 1), time(0, 0))


def test_the_profile_keeps_the_resolved_label_and_coordinates() -> None:
    profile = _service().build_profile(MOSCOW, date(2000, 3, 3), time(9, 15))

    assert profile.birth_place == "Москва, Россия"
    assert profile.timezone == "Europe/Moscow"
    assert profile.latitude == pytest.approx(55.755864)
    assert profile.longitude == pytest.approx(37.617698)


@pytest.mark.parametrize("query", ["", " ", "я", "  " + "г" * 201])
async def test_a_query_outside_the_allowed_length_never_reaches_the_provider(
    query: str,
) -> None:
    with pytest.raises(InvalidBirthPlaceQueryError):
        await _service().search(query)


async def test_search_collapses_whitespace_before_matching() -> None:
    places = await _service().search("  Санкт-Петербург   ")

    assert places and places[0].timezone == "Europe/Moscow"


async def test_search_is_capped_at_the_candidate_limit() -> None:
    service = BirthPlaceLookupService(StubGeocodingClient(), max_candidates=2)

    assert len(await service.search("россия")) <= 2


def test_a_repeated_hour_is_never_resolved_by_guessing() -> None:
    """1991-09-29 02:30 happened twice in Paris; one hour moves the ascendant."""
    with pytest.raises(AmbiguousBirthTimeError) as captured:
        _service().build_profile(PARIS, date(1991, 9, 29), time(2, 30))

    assert captured.value.offsets == (60, 120)


def test_the_chosen_offset_decides_the_calculated_moment() -> None:
    service = _service()

    winter = service.build_profile(PARIS, date(1991, 9, 29), time(2, 30), 60)
    summer = service.build_profile(PARIS, date(1991, 9, 29), time(2, 30), 120)

    assert winter.utc_calculation_datetime().hour == 1
    assert summer.utc_calculation_datetime().hour == 0


def test_an_offset_that_never_applied_is_refused() -> None:
    with pytest.raises(UnresolvableBirthPlaceError):
        _service().build_profile(PARIS, date(1991, 9, 29), time(2, 30), 999)


def test_candidate_offsets_reports_the_gap_the_repeat_and_the_ordinary_case() -> None:
    service = _service()

    assert service.candidate_offsets(MOSCOW, date(1981, 4, 1), time(0, 0)) == ()
    assert service.candidate_offsets(PARIS, date(1991, 9, 29), time(2, 30)) == (60, 120)
    assert service.candidate_offsets(MOSCOW, date(2020, 7, 12), time(14, 30)) == (180,)


def test_a_future_birth_date_is_refused_before_anything_else() -> None:
    future = date(datetime.now(UTC).year + 5, 7, 12)

    with pytest.raises(UnresolvableBirthPlaceError, match="future"):
        _service().build_profile(MOSCOW, future, time(14, 30))


def test_an_unknown_time_stays_unambiguous_at_local_noon() -> None:
    assert len(_service().candidate_offsets(PARIS, date(1991, 9, 29), None)) == 1
