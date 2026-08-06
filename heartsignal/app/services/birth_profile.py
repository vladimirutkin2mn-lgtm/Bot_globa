"""Transactional explicit-consent service for encrypted birth profiles."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TypeVar, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.birth_profile_models import (
    BirthProfile,
    BirthProfileConsent,
    BirthProfilePrivateContent,
)
from app.db.models import User
from app.domain.birth_profile import (
    CURRENT_BIRTH_PROFILE_CONSENT_VERSION,
    CURRENT_BIRTH_PROFILE_FORMAT_VERSION,
    CURRENT_BIRTH_PROFILE_VERSION,
    BirthProfileConsentStatus,
    BirthProfileConsentView,
    BirthProfileInput,
    BirthProfileStatus,
    BirthProfileView,
)
from app.providers.analytics import OracleProductEvent
from app.services.oracle_product_analytics import (
    OracleAnalyticsValue,
    OracleProductAnalytics,
)
from app.services.sensitive_content import ContentPurpose, SensitiveContentCipher

logger = logging.getLogger(__name__)
T = TypeVar("T")


class BirthProfileConsentRequiredError(PermissionError):
    """Safe error raised when birth profile storage has not been authorized."""


class BirthProfileService:
    """Serialize consent and profile writes while keeping all birth details encrypted."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        cipher: SensitiveContentCipher,
        *,
        consent_version: str = CURRENT_BIRTH_PROFILE_CONSENT_VERSION,
        profile_version: str = CURRENT_BIRTH_PROFILE_VERSION,
        analytics: OracleProductAnalytics | None = None,
    ) -> None:
        self._sessions = sessions
        self._cipher = cipher
        self._consent_version = consent_version
        self._profile_version = profile_version
        self._analytics = analytics

    async def consent_state(self, user_id: UUID) -> BirthProfileConsentView | None:
        async with self._sessions() as session:
            consent = await session.get(BirthProfileConsent, user_id)
            return self._consent_view(consent) if consent is not None else None

    async def grant_consent(self, user_id: UUID) -> BirthProfileConsentView:
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            await self._required_active_user(session, user_id, for_update=True)
            consent = await session.get(BirthProfileConsent, user_id, with_for_update=True)
            if consent is None:
                consent = BirthProfileConsent(
                    user_id=user_id,
                    status=BirthProfileConsentStatus.GRANTED.value,
                    consent_version=self._consent_version,
                    accepted_at=now,
                    revoked_at=None,
                )
                session.add(consent)
            elif not self._permits_profile(consent):
                consent.status = BirthProfileConsentStatus.GRANTED.value
                consent.consent_version = self._consent_version
                consent.accepted_at = now
                consent.revoked_at = None
            await session.flush()
            view = self._consent_view(consent)
        await self._track(
            user_id,
            OracleProductEvent.BIRTH_PROFILE_CONSENT_GRANTED,
            {"consent_version": self._consent_version},
        )
        return view

    async def revoke_consent(self, user_id: UUID) -> BirthProfileConsentView:
        now = datetime.now(UTC)
        deleted_version: str | None = None
        async with self._sessions.begin() as session:
            await self._required_active_user(session, user_id, for_update=True)
            consent = await session.get(BirthProfileConsent, user_id, with_for_update=True)
            if consent is None:
                consent = BirthProfileConsent(
                    user_id=user_id,
                    status=BirthProfileConsentStatus.REVOKED.value,
                    consent_version=self._consent_version,
                    accepted_at=None,
                    revoked_at=now,
                )
                session.add(consent)
            elif consent.status != BirthProfileConsentStatus.REVOKED.value:
                consent.status = BirthProfileConsentStatus.REVOKED.value
                consent.revoked_at = now
            profile = await self._profile_locked(session, user_id)
            if profile is not None:
                deleted_version = profile.profile_version
                await self._purge_profile(session, profile, now)
            await session.flush()
            view = self._consent_view(consent)
        await self._track(
            user_id,
            OracleProductEvent.BIRTH_PROFILE_CONSENT_REVOKED,
            {"consent_version": self._consent_version},
        )
        if deleted_version is not None:
            await self._track(
                user_id,
                OracleProductEvent.BIRTH_PROFILE_DELETED,
                {"profile_version": deleted_version},
            )
        return view

    async def save(self, user_id: UUID, value: BirthProfileInput) -> BirthProfileView:
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            await self._required_active_user(session, user_id, for_update=True)
            consent = await session.get(BirthProfileConsent, user_id, with_for_update=True)
            if not self._permits_profile(consent):
                raise BirthProfileConsentRequiredError(
                    "explicit birth profile consent is required"
                )
            ciphertext = self._cipher.encrypt_json(
                ContentPurpose.BIRTH_PROFILE,
                value.encrypted_payload(),
            )
            profile = await self._profile_locked(session, user_id)
            if profile is None:
                profile = BirthProfile(
                    user_id=user_id,
                    status=BirthProfileStatus.ACTIVE.value,
                    profile_version=self._profile_version,
                    deleted_at=None,
                )
                session.add(profile)
                await session.flush()
                private = BirthProfilePrivateContent(
                    birth_profile_id=profile.id,
                    payload_ciphertext=ciphertext,
                    payload_format_version=CURRENT_BIRTH_PROFILE_FORMAT_VERSION,
                    content_deleted_at=None,
                )
                session.add(private)
            else:
                profile.status = BirthProfileStatus.ACTIVE.value
                profile.profile_version = self._profile_version
                profile.deleted_at = None
                private = await session.get(
                    BirthProfilePrivateContent,
                    profile.id,
                    with_for_update=True,
                )
                if private is None:
                    private = BirthProfilePrivateContent(birth_profile_id=profile.id)
                    session.add(private)
                private.payload_ciphertext = ciphertext
                private.payload_format_version = CURRENT_BIRTH_PROFILE_FORMAT_VERSION
                private.content_deleted_at = None
                profile.updated_at = now
            await session.flush()
            view = self._profile_view(profile, value)
        await self._track(
            user_id,
            OracleProductEvent.BIRTH_PROFILE_SAVED,
            {
                "profile_version": self._profile_version,
                "time_precision": "exact" if value.time_known else "date_only",
            },
        )
        return view

    async def load(self, user_id: UUID) -> BirthProfileView | None:
        async with self._sessions.begin() as session:
            loaded = await self._authorized_profile_locked(session, user_id)
            if loaded is None:
                return None
            profile, value = loaded
            return self._profile_view(profile, value)

    async def use_profile(
        self,
        user_id: UUID,
        operation: Callable[[BirthProfileInput], T],
    ) -> T | None:
        """Run a synchronous pure operation before the consent lock is released."""
        async with self._sessions.begin() as session:
            loaded = await self._authorized_profile_locked(session, user_id)
            if loaded is None:
                return None
            _, value = loaded
            return operation(value)

    async def delete_profile(self, user_id: UUID) -> bool:
        now = datetime.now(UTC)
        deleted_version: str | None = None
        async with self._sessions.begin() as session:
            await self._required_active_user(session, user_id, for_update=True)
            profile = await self._profile_locked(session, user_id)
            if profile is None:
                return False
            deleted_version = profile.profile_version
            await self._purge_profile(session, profile, now)
            await session.flush()
        await self._track(
            user_id,
            OracleProductEvent.BIRTH_PROFILE_DELETED,
            {"profile_version": deleted_version},
        )
        return True

    async def _authorized_profile_locked(
        self,
        session: AsyncSession,
        user_id: UUID,
    ) -> tuple[BirthProfile, BirthProfileInput] | None:
        await self._required_active_user(session, user_id, for_update=True)
        consent = await session.get(BirthProfileConsent, user_id, with_for_update=True)
        if not self._permits_profile(consent):
            raise BirthProfileConsentRequiredError(
                "explicit birth profile consent is required"
            )
        row = (
            await session.execute(
                select(BirthProfile, BirthProfilePrivateContent)
                .join(
                    BirthProfilePrivateContent,
                    BirthProfilePrivateContent.birth_profile_id == BirthProfile.id,
                )
                .where(
                    BirthProfile.user_id == user_id,
                    BirthProfile.status == BirthProfileStatus.ACTIVE.value,
                    BirthProfilePrivateContent.payload_ciphertext.is_not(None),
                )
                .with_for_update()
            )
        ).one_or_none()
        if row is None:
            return None
        profile, private = row
        assert private.payload_ciphertext is not None
        payload = self._cipher.decrypt_json(
            ContentPurpose.BIRTH_PROFILE,
            private.payload_ciphertext,
        )
        value = BirthProfileInput.from_encrypted_payload(payload)
        return profile, value

    async def _purge_profile(
        self,
        session: AsyncSession,
        profile: BirthProfile,
        now: datetime,
    ) -> None:
        private = await session.get(
            BirthProfilePrivateContent,
            profile.id,
            with_for_update=True,
        )
        if private is not None and private.payload_ciphertext is not None:
            private.payload_ciphertext = None
            private.payload_format_version = None
            private.content_deleted_at = now
        profile.status = BirthProfileStatus.DELETED.value
        profile.deleted_at = now
        profile.updated_at = now

    async def _profile_locked(
        self,
        session: AsyncSession,
        user_id: UUID,
    ) -> BirthProfile | None:
        return cast(
            BirthProfile | None,
            await session.scalar(
                select(BirthProfile)
                .where(BirthProfile.user_id == user_id)
                .with_for_update()
            ),
        )

    async def _required_active_user(
        self,
        session: AsyncSession,
        user_id: UUID,
        *,
        for_update: bool = False,
    ) -> User:
        statement = select(User).where(User.id == user_id, User.privacy_status == "active")
        if for_update:
            statement = statement.with_for_update(of=User)
        user = cast(User | None, await session.scalar(statement))
        if user is None:
            raise LookupError("active birth profile user not found")
        return user

    def _permits_profile(self, consent: BirthProfileConsent | None) -> bool:
        return (
            consent is not None
            and consent.status == BirthProfileConsentStatus.GRANTED.value
            and consent.consent_version == self._consent_version
        )

    @staticmethod
    def _consent_view(consent: BirthProfileConsent) -> BirthProfileConsentView:
        return BirthProfileConsentView(
            status=BirthProfileConsentStatus(consent.status),
            consent_version=consent.consent_version,
            accepted_at=consent.accepted_at,
            revoked_at=consent.revoked_at,
        )

    @staticmethod
    def _profile_view(profile: BirthProfile, value: BirthProfileInput) -> BirthProfileView:
        return BirthProfileView(
            profile=value,
            profile_version=profile.profile_version,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )

    async def _track(
        self,
        user_id: UUID,
        event: OracleProductEvent,
        properties: dict[str, OracleAnalyticsValue | None],
    ) -> None:
        if self._analytics is None:
            return
        try:
            await self._analytics.track(user_id, event, properties)
        except Exception:
            logger.warning("oracle_analytics_failed event=%s", event.value)
