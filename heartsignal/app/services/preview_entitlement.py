"""Concurrency-safe one-time free preview entitlement shared by all products."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Analysis, User
from app.db.reading_models import Reading
from app.domain.reading import ReadingAccess, ReadingStatus


class PreviewOutcome(StrEnum):
    RESERVED = "reserved"
    ALREADY_RESERVED_SAME_ANALYSIS = "already_reserved_same_analysis"
    ALREADY_CONSUMED_SAME_ANALYSIS = "already_consumed_same_analysis"
    ALREADY_RESERVED_SAME_READING = "already_reserved_same_reading"
    ALREADY_CONSUMED_SAME_READING = "already_consumed_same_reading"
    CONSUMED = "consumed"
    RELEASED = "released"
    UNAVAILABLE = "unavailable"
    ANALYSIS_NOT_FOUND = "analysis_not_found"
    READING_NOT_FOUND = "reading_not_found"
    USER_NOT_FOUND = "user_not_found"
    NOT_READY = "not_ready"
    RELEASED_AFTER_FAILURE = "released_after_failure"
    RELEASED_AFTER_DELETION = "released_after_deletion"


class ReadingPreviewVisibility(StrEnum):
    PREVIEW = "preview"
    FULL = "full"
    LOCKED = "locked"
    PENDING = "pending"


@dataclass(frozen=True)
class PreviewState:
    status: str
    analysis_id: UUID | None
    reading_id: UUID | None


class PreviewEntitlementService:
    """Serialize the single free preview using the durable user row."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get_preview_state(self, user_id: UUID) -> PreviewState | None:
        async with self._sessions() as session:
            user = await session.get(User, user_id)
            return (
                None
                if user is None
                else PreviewState(
                    user.free_preview_status,
                    user.free_preview_analysis_id,
                    user.free_preview_reading_id,
                )
            )

    async def reserve_preview(self, user_id: UUID, analysis_id: UUID) -> PreviewOutcome:
        async with self._sessions.begin() as session:
            user = await session.scalar(select(User).where(User.id == user_id).with_for_update())
            if user is None:
                return PreviewOutcome.USER_NOT_FOUND
            analysis = await session.scalar(
                select(Analysis).where(Analysis.id == analysis_id, Analysis.user_id == user_id)
            )
            if analysis is None:
                return PreviewOutcome.ANALYSIS_NOT_FOUND
            if user.free_preview_analysis_id == analysis_id:
                if user.free_preview_status == "reserved" and analysis.status in {
                    "deleted",
                    "failed",
                }:
                    self._make_available(user)
                    return (
                        PreviewOutcome.RELEASED_AFTER_DELETION
                        if analysis.status == "deleted"
                        else PreviewOutcome.RELEASED_AFTER_FAILURE
                    )
                return (
                    PreviewOutcome.ALREADY_CONSUMED_SAME_ANALYSIS
                    if user.free_preview_status == "consumed"
                    else PreviewOutcome.ALREADY_RESERVED_SAME_ANALYSIS
                )
            if analysis.status != "draft" or analysis.intake_step != "complete":
                return PreviewOutcome.NOT_READY
            if user.free_preview_status != "available":
                return PreviewOutcome.UNAVAILABLE
            user.free_preview_status = "reserved"
            user.free_preview_analysis_id = analysis_id
            user.free_preview_reading_id = None
            return PreviewOutcome.RESERVED

    async def reserve_reading_preview(self, user_id: UUID, reading_id: UUID) -> PreviewOutcome:
        async with self._sessions.begin() as session:
            user = await session.scalar(select(User).where(User.id == user_id).with_for_update())
            if user is None:
                return PreviewOutcome.USER_NOT_FOUND
            reading = await session.scalar(
                select(Reading).where(Reading.id == reading_id, Reading.user_id == user_id)
            )
            if reading is None:
                return PreviewOutcome.READING_NOT_FOUND
            if user.free_preview_reading_id == reading_id:
                if user.free_preview_status == "reserved" and reading.status in {
                    ReadingStatus.DELETED.value,
                    ReadingStatus.FAILED.value,
                }:
                    self._make_available(user)
                    return (
                        PreviewOutcome.RELEASED_AFTER_DELETION
                        if reading.status == ReadingStatus.DELETED.value
                        else PreviewOutcome.RELEASED_AFTER_FAILURE
                    )
                return (
                    PreviewOutcome.ALREADY_CONSUMED_SAME_READING
                    if user.free_preview_status == "consumed"
                    else PreviewOutcome.ALREADY_RESERVED_SAME_READING
                )
            if reading.status not in {ReadingStatus.DRAFT.value, ReadingStatus.FAILED.value}:
                return PreviewOutcome.NOT_READY
            if user.free_preview_status != "available":
                return PreviewOutcome.UNAVAILABLE
            user.free_preview_status = "reserved"
            user.free_preview_analysis_id = None
            user.free_preview_reading_id = reading_id
            return PreviewOutcome.RESERVED

    async def consume_preview(self, user_id: UUID, analysis_id: UUID) -> PreviewOutcome:
        return await self._transition_analysis(user_id, analysis_id, consume=True)

    async def finalize_preview(self, user_id: UUID, analysis_id: UUID) -> PreviewOutcome:
        """Consume the entitlement without ever downgrading durable report access."""
        async with self._sessions.begin() as session:
            user = await session.scalar(select(User).where(User.id == user_id).with_for_update())
            if user is None:
                return PreviewOutcome.USER_NOT_FOUND
            analysis = await session.scalar(
                select(Analysis)
                .where(Analysis.id == analysis_id, Analysis.user_id == user_id)
                .with_for_update()
            )
            if analysis is None:
                return PreviewOutcome.ANALYSIS_NOT_FOUND
            if analysis.status != "completed":
                return PreviewOutcome.NOT_READY
            if (
                user.free_preview_status != "reserved"
                or user.free_preview_analysis_id != analysis_id
            ):
                return PreviewOutcome.UNAVAILABLE
            if analysis.report_access != "full":
                analysis.report_access = "preview"
                analysis.cost_units = 0
                analysis.full_access_transaction_id = None
            self._consume(user)
            await session.flush()
            return PreviewOutcome.CONSUMED

    async def resolve_reading_visibility(
        self,
        user_id: UUID,
        reading_id: UUID,
    ) -> ReadingPreviewVisibility:
        """Finalize a reserved ready preview or return the durable paywall visibility."""
        async with self._sessions.begin() as session:
            user = await session.scalar(select(User).where(User.id == user_id).with_for_update())
            if user is None:
                return ReadingPreviewVisibility.LOCKED
            reading = await session.scalar(
                select(Reading)
                .where(Reading.id == reading_id, Reading.user_id == user_id)
                .with_for_update()
            )
            if reading is None:
                return ReadingPreviewVisibility.LOCKED
            if (
                reading.status == ReadingStatus.FULL_READY.value
                and reading.access_level == ReadingAccess.FULL.value
            ):
                if (
                    user.free_preview_status == "reserved"
                    and user.free_preview_reading_id == reading_id
                ):
                    self._make_available(user)
                return ReadingPreviewVisibility.FULL
            if user.free_preview_reading_id != reading_id:
                return ReadingPreviewVisibility.LOCKED
            if user.free_preview_status == "consumed":
                return (
                    ReadingPreviewVisibility.PREVIEW
                    if reading.status == ReadingStatus.PREVIEW_READY.value
                    else ReadingPreviewVisibility.LOCKED
                )
            if user.free_preview_status != "reserved":
                return ReadingPreviewVisibility.LOCKED
            if reading.status == ReadingStatus.PREVIEW_READY.value:
                self._consume(user)
                return ReadingPreviewVisibility.PREVIEW
            if reading.status in {ReadingStatus.FAILED.value, ReadingStatus.DELETED.value}:
                self._make_available(user)
                return ReadingPreviewVisibility.LOCKED
            return ReadingPreviewVisibility.PENDING

    async def release_preview(self, user_id: UUID, analysis_id: UUID) -> PreviewOutcome:
        return await self._transition_analysis(user_id, analysis_id, consume=False)

    async def release_reading_preview(self, user_id: UUID, reading_id: UUID) -> PreviewOutcome:
        async with self._sessions.begin() as session:
            user = await session.scalar(select(User).where(User.id == user_id).with_for_update())
            if user is None:
                return PreviewOutcome.USER_NOT_FOUND
            if (
                user.free_preview_reading_id != reading_id
                or user.free_preview_status != "reserved"
            ):
                return PreviewOutcome.UNAVAILABLE
            self._make_available(user)
            return PreviewOutcome.RELEASED

    async def _transition_analysis(
        self,
        user_id: UUID,
        analysis_id: UUID,
        *,
        consume: bool,
    ) -> PreviewOutcome:
        async with self._sessions.begin() as session:
            user = await session.scalar(select(User).where(User.id == user_id).with_for_update())
            if user is None:
                return PreviewOutcome.USER_NOT_FOUND
            if (
                user.free_preview_analysis_id != analysis_id
                or user.free_preview_status != "reserved"
            ):
                return PreviewOutcome.UNAVAILABLE
            if consume:
                self._consume(user)
                return PreviewOutcome.CONSUMED
            self._make_available(user)
            return PreviewOutcome.RELEASED

    @staticmethod
    def _consume(user: User) -> None:
        user.free_preview_status = "consumed"
        user.free_preview_used_at = datetime.now(UTC)

    @staticmethod
    def _make_available(user: User) -> None:
        user.free_preview_status = "available"
        user.free_preview_analysis_id = None
        user.free_preview_reading_id = None
        user.free_preview_used_at = None
