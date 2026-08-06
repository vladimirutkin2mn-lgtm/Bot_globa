"""Pure contract tests for encrypted BirthProfile payloads."""

from datetime import UTC, date, time, timedelta
from typing import cast

import pytest

from app.domain.birth_profile import BirthProfileInput


def _values() -> dict[str, object]:
    return {
        "birth_date": date(1991, 4, 17),
        "birth_time": time(8, 35),
        "birth_place": "Amsterdam",
        "timezone": "Europe/Amsterdam",
        "latitude": 52.3675734,
        "longitude": 4.9041389,
        "utc_offset_minutes": 120,
    }


def test_birth_profile_round_trips_exact_and_unknown_time() -> None:
    exact = BirthProfileInput(
        birth_date=date(1991, 4, 17),
        birth_time=time(8, 35, 30),
        birth_place="  Amsterdam   Centrum  ",
        timezone="Europe/Amsterdam",
        latitude=52.3675734,
        longitude=4.9041389,
        utc_offset_minutes=120,
    )
    unknown = BirthProfileInput(
        birth_date=date(1991, 4, 17),
        birth_time=None,
        birth_place="Amsterdam Centrum",
        timezone="Europe/Amsterdam",
        latitude=52.3675734,
        longitude=4.9041389,
        utc_offset_minutes=120,
    )

    assert exact.birth_place == "Amsterdam Centrum"
    assert exact.latitude == 52.367573
    assert exact.longitude == 4.904139
    assert exact.utc_calculation_datetime().isoformat() == "1991-04-17T06:35:30+00:00"
    assert unknown.utc_calculation_datetime().isoformat() == "1991-04-17T10:00:00+00:00"
    assert BirthProfileInput.from_encrypted_payload(exact.encrypted_payload()) == exact
    assert BirthProfileInput.from_encrypted_payload(unknown.encrypted_payload()) == unknown


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"birth_place": ""}, "birth place"),
        ({"timezone": "Not/A_Timezone"}, "valid IANA timezone"),
        ({"birth_date": date.today() + timedelta(days=1)}, "cannot be in the future"),
        ({"birth_time": time(12, tzinfo=UTC)}, "timezone-naive"),
        ({"latitude": 90.1}, "between -90 and 90"),
        ({"longitude": -180.1}, "between -180 and 180"),
        ({"latitude": float("nan")}, "finite"),
        ({"utc_offset_minutes": 0}, "inconsistent"),
    ],
)
def test_birth_profile_rejects_invalid_private_fields(
    changes: dict[str, object],
    message: str,
) -> None:
    values = _values()
    values.update(changes)

    with pytest.raises(ValueError, match=message):
        BirthProfileInput(
            birth_date=cast(date, values["birth_date"]),
            birth_time=cast(time | None, values["birth_time"]),
            birth_place=cast(str, values["birth_place"]),
            timezone=cast(str, values["timezone"]),
            latitude=cast(float, values["latitude"]),
            longitude=cast(float, values["longitude"]),
            utc_offset_minutes=cast(int, values["utc_offset_minutes"]),
        )


def test_birth_profile_rejects_nonexistent_local_time() -> None:
    with pytest.raises(ValueError, match="does not exist"):
        BirthProfileInput(
            birth_date=date(2025, 3, 30),
            birth_time=time(2, 30),
            birth_place="Amsterdam",
            timezone="Europe/Amsterdam",
            latitude=52.3676,
            longitude=4.9041,
            utc_offset_minutes=60,
        )


def test_birth_profile_uses_offset_to_disambiguate_repeated_local_time() -> None:
    summer_fold = BirthProfileInput(
        birth_date=date(2025, 10, 26),
        birth_time=time(2, 30),
        birth_place="Amsterdam",
        timezone="Europe/Amsterdam",
        latitude=52.3676,
        longitude=4.9041,
        utc_offset_minutes=120,
    )
    winter_fold = BirthProfileInput(
        birth_date=date(2025, 10, 26),
        birth_time=time(2, 30),
        birth_place="Amsterdam",
        timezone="Europe/Amsterdam",
        latitude=52.3676,
        longitude=4.9041,
        utc_offset_minutes=60,
    )

    assert summer_fold.utc_calculation_datetime().isoformat() == "2025-10-26T00:30:00+00:00"
    assert winter_fold.utc_calculation_datetime().isoformat() == "2025-10-26T01:30:00+00:00"


def test_birth_profile_rejects_malformed_decrypted_shape() -> None:
    with pytest.raises(ValueError, match="shape"):
        BirthProfileInput.from_encrypted_payload("not-a-profile")
    with pytest.raises(ValueError, match="fields"):
        BirthProfileInput.from_encrypted_payload({"birth_date": "1991-04-17"})
