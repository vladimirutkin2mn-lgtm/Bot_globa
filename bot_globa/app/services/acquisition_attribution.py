"""Partizan first-touch token and persistence helpers.

This module has no network dependency on Partizan. It only translates the
minimal experiment identifier that is safe to carry through a Telegram start
payload and persists the first observed attribution atomically.
"""

import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.acquisition_models import AcquisitionAttribution
from app.db.models import User
from app.repositories.users import UserRepository

_PARTIZAN_START_RE = re.compile(r"^ptz_([0-9a-f]{32})$")


def encode_partizan_start_payload(experiment_id: UUID) -> str:
    """Encode one Partizan experiment UUID into a compact Telegram payload."""

    return f"ptz_{experiment_id.hex}"


def parse_partizan_start_payload(payload: str | None) -> UUID | None:
    """Return the attributed experiment for a valid Oracle/Partizan payload."""

    if payload is None:
        return None
    match = _PARTIZAN_START_RE.fullmatch(payload.strip())
    if match is None:
        return None
    return UUID(hex=match.group(1))


def parse_partizan_start_command(text: str | None) -> UUID | None:
    """Extract only a strict Partizan payload from a Telegram `/start` command."""

    if not text:
        return None
    command, separator, arguments = text.strip().partition(" ")
    if command.partition("@")[0].casefold() != "/start" or not separator:
        return None
    return parse_partizan_start_payload(arguments)


class AcquisitionAttributionRepository:
    """Capture immutable first-touch attribution with concurrency safety."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def capture_first_touch(
        self, *, user_id: UUID, experiment_id: UUID
    ) -> tuple[AcquisitionAttribution, bool]:
        statement = (
            insert(AcquisitionAttribution)
            .values(
                user_id=user_id,
                source="partizan",
                experiment_id=experiment_id,
            )
            .on_conflict_do_nothing(index_elements=[AcquisitionAttribution.user_id])
            .returning(AcquisitionAttribution.user_id)
        )
        inserted_user_id = (await self._session.execute(statement)).scalar_one_or_none()
        await self._session.commit()
        attribution = await self.get_for_user(user_id)
        if attribution is None:  # pragma: no cover - protected by the database constraint
            raise RuntimeError("Attribution insert did not produce a persisted first-touch row")
        return attribution, inserted_user_id is not None

    async def get_for_user(self, user_id: UUID) -> AcquisitionAttribution | None:
        result = await self._session.execute(
            select(AcquisitionAttribution).where(AcquisitionAttribution.user_id == user_id)
        )
        return result.scalar_one_or_none()


class AttributingUserRepository:
    """Decorate onboarding persistence with one immutable Partizan first touch."""

    def __init__(
        self,
        users: UserRepository,
        attributions: AcquisitionAttributionRepository,
        experiment_id: UUID,
    ) -> None:
        self._users = users
        self._attributions = attributions
        self._experiment_id = experiment_id

    async def get_or_create(
        self,
        telegram_user_id: int,
        username: str | None,
        first_name: str,
        language: str | None,
    ) -> tuple[User, bool]:
        user, created = await self._users.get_or_create(
            telegram_user_id,
            username,
            first_name,
            language,
        )
        await self._attributions.capture_first_touch(
            user_id=user.id,
            experiment_id=self._experiment_id,
        )
        return user, created

    async def get_by_telegram_id(self, telegram_user_id: int) -> User | None:
        return await self._users.get_by_telegram_id(telegram_user_id)

    async def save(self, user: User) -> None:
        await self._users.save(user)
