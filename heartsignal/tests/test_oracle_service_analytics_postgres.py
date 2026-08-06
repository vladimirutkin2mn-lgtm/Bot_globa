"""Real service transitions emit content-free oracle product events."""

from datetime import date, time
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.analytics import AnalyticsEvent
from app.db.models import User
from app.db.reading_models import Persona
from app.domain.birth_profile import BirthProfileInput
from app.domain.reading import ReadingDraftRequest
from app.observability.context import reset_correlation_id, set_correlation_id
from app.providers.analytics_postgres import PostgresAnalyticsClient
from app.services.birth_profile import BirthProfileService
from app.services.oracle_product_analytics import OracleProductAnalytics
from app.services.reading_service import ReadingService
from app.services.sensitive_content import AESGCMSensitiveContentCipher
from tests.payment_postgres_helpers import payment_db  # noqa: F401


async def test_reading_and_birth_profile_emit_only_safe_metadata(
    payment_db: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    async with payment_db.begin() as session:
        user = User(telegram_user_id=uuid4().int % 10**12, first_name="Analytics User")
        persona = Persona(
            code="analytics_tarot",
            display_name="Analytics Tarot",
            prompt_version="analytics-prompt-v1",
            schema_version="reading-result-v1",
        )
        session.add_all((user, persona))
        await session.flush()
        user_id = user.id

    cipher = AESGCMSensitiveContentCipher("oracle-analytics-service-test-key")
    analytics = OracleProductAnalytics(PostgresAnalyticsClient(payment_db))
    readings = ReadingService(payment_db, cipher, analytics=analytics)
    profiles = BirthProfileService(payment_db, cipher, analytics=analytics)

    _, token = set_correlation_id("reading-service-transition")
    try:
        reading = await readings.create_draft(
            user_id,
            ReadingDraftRequest(
                persona_code="analytics_tarot",
                topic="decision",
                question="PRIVATE-QUESTION-MUST-NOT-ENTER-ANALYTICS",
                context="PRIVATE-CONTEXT-MUST-NOT-ENTER-ANALYTICS",
                engine_version="symbolic-v1",
                prompt_version="analytics-prompt-v1",
                schema_version="reading-result-v1",
                cost_units=0,
            ),
        )
    finally:
        reset_correlation_id(token)

    _, token = set_correlation_id("birth-consent-transition")
    try:
        await profiles.grant_consent(user_id)
    finally:
        reset_correlation_id(token)

    _, token = set_correlation_id("birth-save-transition")
    try:
        await profiles.save(
            user_id,
            BirthProfileInput(
                birth_date=date(1991, 4, 17),
                birth_time=time(8, 35),
                birth_place="Amsterdam",
                timezone="Europe/Amsterdam",
                latitude=52.367573,
                longitude=4.904139,
                utc_offset_minutes=120,
            ),
        )
    finally:
        reset_correlation_id(token)

    _, token = set_correlation_id("birth-delete-transition")
    try:
        assert await profiles.delete_profile(user_id)
    finally:
        reset_correlation_id(token)

    async with payment_db() as session:
        rows = list(
            (
                await session.scalars(
                    select(AnalyticsEvent).order_by(AnalyticsEvent.created_at)
                )
            ).all()
        )

    assert {row.event_name for row in rows} == {
        "reading_started",
        "birth_profile_consent_granted",
        "birth_profile_saved",
        "birth_profile_deleted",
    }
    reading_event = next(row for row in rows if row.event_name == "reading_started")
    assert reading_event.properties["reading_id"] == str(reading.id)
    assert reading_event.properties["persona_code"] == "analytics_tarot"
    assert reading_event.properties["topic_code"] == "decision"
    assert all(row.subject_id == str(user_id) for row in rows)
    serialized = str([row.properties for row in rows])
    for private_value in (
        "PRIVATE-QUESTION-MUST-NOT-ENTER-ANALYTICS",
        "PRIVATE-CONTEXT-MUST-NOT-ENTER-ANALYTICS",
        "1991-04-17",
        "08:35",
        "Amsterdam",
        "Europe/Amsterdam",
        "52.367573",
        "4.904139",
    ):
        assert private_value not in serialized
