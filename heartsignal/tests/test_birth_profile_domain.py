"""Pure contract tests for encrypted BirthProfile payloads."""

from datetime import UTC, date, time, timedelta
from typing import cast

import pytest

from app.domain.birth_profile import BirthProfileInput


def test_birth_profile_round_trips_exact_and_unknown_time() -> None:
    exact = BirthProfileInput(
        birth_date=date(1995, 12, 3),
        birth_time=time(21, 15, 30),
        birth_place="  São Paulo  ",
        timezone="America/Sao_Paulo",
    )
    unknown = BirthProfileInput(
        birth_date=date(1995, 12, 3),
        birth_time=None,
        birth_place="São Paulo",
        timezone="America/Sao_Paulo",
    )

    assert exact.birth_place == "São Paulo"
    assert BirthProfileInput.from_encrypted_payload(exact.encrypted_payload()) == exact
    assert BirthProfileInput.from_encrypted_payload(unknown.encrypted_payload()) == unknown


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"birth_place": ""}, "birth place"),
        ({"timezone": "Not/A_Timezone"}, "valid IANA timezone"),
        ({"birth_date": date.today() + timedelta(days=1)}, "cannot be in the future"),
        ({"birth_time": time(12, tzinfo=UTC)}, "timezone-naive"),
    ],
)
def test_birth_profile_rejects_invalid_private_fields(
    changes: dict[str, object],
    message: str,
) -> None:
    values: dict[str, object] = {
        "birth_date": date(1995, 12, 3),
        "birth_time": time(21, 15),
        "birth_place": "São Paulo",
        "timezone": "America/Sao_Paulo",
    }
    values.update(changes)

    with pytest.raises(ValueError, match=message):
        BirthProfileInput(
            birth_date=cast(date, values["birth_date"]),
            birth_time=cast(time | None, values["birth_time"]),
            birth_place=cast(str, values["birth_place"]),
            timezone=cast(str, values["timezone"]),
        )


def test_birth_profile_rejects_malformed_decrypted_shape() -> None:
    with pytest.raises(ValueError, match="shape"):
        BirthProfileInput.from_encrypted_payload("not-a-profile")
    with pytest.raises(ValueError, match="fields"):
        BirthProfileInput.from_encrypted_payload({"birth_date": "1995-12-03"})
