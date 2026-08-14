"""Unit coverage for the minimal Partizan -> Telegram start payload."""

from uuid import UUID, uuid4

from app.db.models import User
from app.services.acquisition_attribution import (
    AttributingUserRepository,
    encode_partizan_start_payload,
    parse_partizan_start_command,
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

    assert parse_partizan_start_payload(f"ptz_{experiment_id.hex}&utm_source=telegram") is None


def test_telegram_start_command_accepts_only_the_minimal_partizan_payload() -> None:
    experiment_id = uuid4()
    payload = encode_partizan_start_payload(experiment_id)

    assert parse_partizan_start_command(f"/start {payload}") == experiment_id
    assert parse_partizan_start_command(f"/start@NumaOracleBot {payload}") == experiment_id
    assert parse_partizan_start_command("/start") is None
    assert parse_partizan_start_command(f"/help {payload}") is None
    assert parse_partizan_start_command(f"/start {payload} extra") is None
    assert parse_partizan_start_command(f"/start {payload}&utm_source=telegram") is None


class _UserRepositoryDouble:
    def __init__(self, user: User) -> None:
        self.user = user
        self.calls = 0

    async def get_or_create(
        self,
        telegram_user_id: int,
        username: str | None,
        first_name: str,
        language: str | None,
    ) -> tuple[User, bool]:
        self.calls += 1
        return self.user, True

    async def get_by_telegram_id(self, telegram_user_id: int) -> User | None:
        return self.user

    async def save(self, user: User) -> None:
        self.user = user


class _AttributionRepositoryDouble:
    def __init__(self) -> None:
        self.captured: list[tuple[UUID, UUID]] = []

    async def capture_first_touch(self, *, user_id: UUID, experiment_id: UUID) -> tuple[object, bool]:
        self.captured.append((user_id, experiment_id))
        return object(), True


async def test_onboarding_user_creation_captures_partizan_first_touch() -> None:
    user = User(
        id=uuid4(),
        telegram_user_id=123,
        telegram_username="oracle_user",
        first_name="Oracle",
        telegram_language="en",
    )
    users = _UserRepositoryDouble(user)
    attributions = _AttributionRepositoryDouble()
    experiment_id = uuid4()
    repository = AttributingUserRepository(users, attributions, experiment_id)  # type: ignore[arg-type]

    returned, created = await repository.get_or_create(123, "oracle_user", "Oracle", "en")

    assert returned is user
    assert created is True
    assert users.calls == 1
    assert attributions.captured == [(user.id, experiment_id)]
