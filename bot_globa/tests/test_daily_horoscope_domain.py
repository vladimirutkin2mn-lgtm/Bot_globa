"""Pure validation for the user-entered time difference from Moscow."""

import pytest

from app.domain.daily_horoscope import (
    moscow_time_difference_for_timezone,
    parse_moscow_time_difference,
    timezone_for_moscow_time_difference,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    (("0", 0), ("+2", 2), (" -1 ", -1), ("−3", -3), ("+11", 11), ("-15", -15)),
)
def test_parse_moscow_time_difference_accepts_signed_whole_hours(
    raw: str,
    expected: int,
) -> None:
    assert parse_moscow_time_difference(raw) == expected


@pytest.mark.parametrize("raw", ("", "+2.5", "UTC+2", "+12", "-16", "два"))
def test_parse_moscow_time_difference_rejects_ambiguous_or_impossible_values(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_moscow_time_difference(raw)


@pytest.mark.parametrize(
    ("difference", "timezone"),
    ((0, "Etc/GMT-3"), (2, "Etc/GMT-5"), (-1, "Etc/GMT-2"), (-3, "Etc/GMT")),
)
def test_fixed_timezone_round_trips_the_moscow_difference(
    difference: int,
    timezone: str,
) -> None:
    assert timezone_for_moscow_time_difference(difference) == timezone
    assert moscow_time_difference_for_timezone(timezone) == difference


def test_legacy_moscow_timezone_displays_as_zero_difference() -> None:
    assert moscow_time_difference_for_timezone("Europe/Moscow") == 0
