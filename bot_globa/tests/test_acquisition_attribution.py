"""Unit coverage for the minimal Partizan -> Telegram start payload."""

from uuid import UUID, uuid4

from app.services.acquisition_attribution import (
    encode_partizan_start_payload,
    parse_partizan_start_payload,
)


def test_partizan_start_payload_round_trips_experiment_uuid() -> None:
    experiment_id = uuid4()

    payload = encode_partizan_start_payload(experiment_id)

    assert payload == f"ptz_{experiment_id.hex}"
    assert len(payload) == 36
    assert parse_partizan_start_payload(payload) == experiment_id


def test_partizan_start_payload_rejects_non_partizan_or_malformed_values() -> None:
    valid = uuid4()

    assert parse_partizan_start_payload(None) is None
    assert parse_partizan_start_payload("") is None
    assert parse_partizan_start_payload(str(valid)) is None
    assert parse_partizan_start_payload(f"ptz_{valid}") is None
    assert parse_partizan_start_payload("ptz_" + "g" * 32) is None
    assert parse_partizan_start_payload("other_" + valid.hex) is None


def test_parser_does_not_accept_extra_tracking_data() -> None:
    experiment_id = UUID("f65824e6-c9ca-4988-b486-2f3f8e2299e0")

    assert parse_partizan_start_payload(
        f"ptz_{experiment_id.hex}&utm_source=telegram"
    ) is None
