"""PostgreSQL invariants for explicit-consent encrypted birth profiles."""

import asyncio
from datetime import date, time

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.birth_profile_models import (
    BirthProfile,
    BirthProfileConsent,
    BirthProfilePrivateContent,
)
from app.db.models import User
from app.domain.birth_profile import (
    BirthProfileConsentStatus,
    BirthProfileInput,
    BirthProfileStatus,
)
from app.services.birth_profile import (
    BirthProfileConsentRequiredError,
    BirthProfileService,
)
from app.services.sensitive_content import (
    AESGCMSensitiveContentCipher,
    ContentAuthenticationError,
    ContentPurpose,
)

pytestmark = pytest.mark.postgres


async def _user(sessions: async_sessionmaker[AsyncSession], telegram_id: int) -> User:
    async with sessions.begin() as session:
        user = User(telegram_user_id=telegram_id, first_name="Birth Profile")
        session.add(user)
        await session.flush()
        return user


def _profile(place: str = "Amsterdam private marker") -> BirthProfileInput:
    return BirthProfileInput(
        birth_date=date(1991, 4, 17),
        birth_time=time(8, 35),
        birth_place=place,
        timezone="Europe/Amsterdam",
        latitude=52.367573,
        longitude=4.904139,
        utc_offset_minutes=120,
    )


def _london_profile(place: str) -> BirthProfileInput:
    return BirthProfileInput(
        birth_date=date(1991, 4, 17),
        birth_time=None,
        birth_place=place,
        timezone="Europe/London",
        latitude=51.5074,
        longitude=-0.1278,
        utc_offset_minutes=60,
    )


async def test_birth_profile_requires_consent_and_encrypts_every_detail_at_rest(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 896001)
    cipher = AESGCMSensitiveContentCipher("birth-profile-at-rest-key")
    service = BirthProfileService(payment_db, cipher)
    value = _profile()

    with pytest.raises(BirthProfileConsentRequiredError):
        await service.save(user.id, value)

    consent = await service.grant_consent(user.id)
    saved = await service.save(user.id, value)
    loaded = await service.load(user.id)

    assert consent.status is BirthProfileConsentStatus.GRANTED
    assert saved.profile == value
    assert loaded is not None and loaded.profile == value
    async with payment_db() as session:
        profile = await session.scalar(
            select(BirthProfile).where(BirthProfile.user_id == user.id)
        )
        assert profile is not None
        private = await session.get(BirthProfilePrivateContent, profile.id)
    assert private is not None and private.payload_ciphertext is not None
    ciphertext = private.payload_ciphertext
    for marker in (
        b"1991-04-17",
        b"08:35",
        b"Amsterdam private marker",
        b"Europe/Amsterdam",
        b"52.367573",
        b"4.904139",
        b"120",
    ):
        assert marker not in ciphertext
    assert cipher.decrypt_json(ContentPurpose.BIRTH_PROFILE, ciphertext) == (
        value.encrypted_payload()
    )
    with pytest.raises(ContentAuthenticationError):
        cipher.decrypt_json(ContentPurpose.ORACLE_MEMORY_VALUE, ciphertext)


async def test_save_updates_one_profile_row_and_replaces_ciphertext(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 896002)
    cipher = AESGCMSensitiveContentCipher("birth-profile-upsert-key")
    service = BirthProfileService(payment_db, cipher)
    await service.grant_consent(user.id)
    first = await service.save(user.id, _profile("First private place"))
    second_value = _london_profile("Corrected private place")
    second = await service.save(user.id, second_value)
    loaded = await service.load(user.id)

    assert first.created_at == second.created_at
    assert loaded is not None and loaded.profile == second_value
    async with payment_db() as session:
        count = await session.scalar(
            select(func.count()).select_from(BirthProfile).where(BirthProfile.user_id == user.id)
        )
        profile = await session.scalar(
            select(BirthProfile).where(BirthProfile.user_id == user.id)
        )
        assert profile is not None
        private = await session.get(BirthProfilePrivateContent, profile.id)
    assert count == 1
    assert private is not None and private.payload_ciphertext is not None
    assert b"First private place" not in private.payload_ciphertext
    assert b"Corrected private place" not in private.payload_ciphertext


async def test_concurrent_saves_serialize_to_one_profile_row(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 896008)
    service = BirthProfileService(
        payment_db,
        AESGCMSensitiveContentCipher("birth-profile-concurrent-key"),
    )
    await service.grant_consent(user.id)
    first = _profile("Concurrent private place A")
    second = _london_profile("Concurrent private place B")

    saved = await asyncio.gather(
        service.save(user.id, first),
        service.save(user.id, second),
    )
    loaded = await service.load(user.id)

    assert loaded is not None and loaded.profile in {first, second}
    assert {item.profile for item in saved} == {first, second}
    async with payment_db() as session:
        count = await session.scalar(
            select(func.count()).select_from(BirthProfile).where(BirthProfile.user_id == user.id)
        )
    assert count == 1


async def test_revoke_consent_purges_ciphertext_and_blocks_reuse(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 896003)
    service = BirthProfileService(
        payment_db,
        AESGCMSensitiveContentCipher("birth-profile-revoke-key"),
    )
    await service.grant_consent(user.id)
    await service.save(user.id, _profile())

    consent = await service.revoke_consent(user.id)

    assert consent.status is BirthProfileConsentStatus.REVOKED
    with pytest.raises(BirthProfileConsentRequiredError):
        await service.load(user.id)
    async with payment_db() as session:
        profile = await session.scalar(
            select(BirthProfile).where(BirthProfile.user_id == user.id)
        )
        assert profile is not None
        private = await session.get(BirthProfilePrivateContent, profile.id)
    assert profile.status == BirthProfileStatus.DELETED.value
    assert profile.deleted_at is not None
    assert private is not None and private.payload_ciphertext is None
    assert private.payload_format_version is None
    assert private.content_deleted_at is not None


async def test_user_can_delete_profile_without_revoking_future_consent(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 896004)
    service = BirthProfileService(
        payment_db,
        AESGCMSensitiveContentCipher("birth-profile-delete-key"),
    )
    await service.grant_consent(user.id)
    await service.save(user.id, _profile())

    assert await service.delete_profile(user.id)
    assert await service.load(user.id) is None
    restored = await service.save(user.id, _profile("Restored private place"))

    assert restored.profile.birth_place == "Restored private place"
    consent = await service.consent_state(user.id)
    assert consent is not None and consent.status is BirthProfileConsentStatus.GRANTED


async def test_birth_profile_never_crosses_user_boundary(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    owner = await _user(payment_db, 896005)
    other = await _user(payment_db, 896006)
    service = BirthProfileService(
        payment_db,
        AESGCMSensitiveContentCipher("birth-profile-isolation-key"),
    )
    await service.grant_consent(owner.id)
    await service.grant_consent(other.id)
    await service.save(owner.id, _profile("Owner private place"))

    assert await service.load(other.id) is None
    assert not await service.delete_profile(other.id)
    owner_profile = await service.load(owner.id)
    assert owner_profile is not None
    assert owner_profile.profile.birth_place == "Owner private place"


async def test_account_deletion_cascades_profile_consent_and_ciphertext(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 896007)
    service = BirthProfileService(
        payment_db,
        AESGCMSensitiveContentCipher("birth-profile-account-delete-key"),
    )
    await service.grant_consent(user.id)
    await service.save(user.id, _profile())

    async with payment_db.begin() as session:
        stored = await session.get(User, user.id, with_for_update=True)
        assert stored is not None
        await session.delete(stored)

    async with payment_db() as session:
        assert await session.get(BirthProfileConsent, user.id) is None
        assert (
            await session.scalar(
                select(func.count())
                .select_from(BirthProfile)
                .where(BirthProfile.user_id == user.id)
            )
            == 0
        )
        private_count = await session.scalar(
            select(func.count()).select_from(BirthProfilePrivateContent)
        )
        assert private_count == 0
