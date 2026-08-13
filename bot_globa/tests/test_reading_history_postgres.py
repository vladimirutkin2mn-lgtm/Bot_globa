"""PostgreSQL coverage for safe paginated reading history metadata."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import CreditTransaction, User
from app.db.reading_models import Persona, Reading, ReadingPrivateContent
from app.domain.reading import ReadingAccess, ReadingStatus
from app.services.reading_history import ReadingHistoryService

pytestmark = pytest.mark.postgres


async def test_history_lists_only_owned_ready_persona_rows_in_reverse_order(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    async with payment_db.begin() as session:
        owner = User(telegram_user_id=894001, first_name="HistoryOwner")
        stranger = User(telegram_user_id=894002, first_name="HistoryStranger")
        tarot = Persona(
            code="tarot_reader",
            display_name="Tarot Reader",
            prompt_version="tarot-reader-v1",
            schema_version="reading-result-v1",
        )
        other = Persona(
            code="love_oracle_history",
            display_name="Love Oracle",
            prompt_version="love-oracle-v1",
            schema_version="reading-result-v1",
        )
        session.add_all((owner, stranger, tarot, other))
        await session.flush()

        ready_rows = [
            Reading(
                user_id=owner.id,
                persona_id=tarot.id,
                topic=topic,
                status=ReadingStatus.PREVIEW_READY.value,
                access_level=ReadingAccess.PREVIEW.value,
                cost_units=0,
                engine_version="tarot-symbolic-v1",
                prompt_version="tarot-reader-v1",
                schema_version="reading-result-v1",
                generated_at=now - timedelta(days=index),
                created_at=now - timedelta(days=index),
            )
            for index, topic in enumerate(("decision", "work", "love"))
        ]
        excluded = [
            Reading(
                user_id=owner.id,
                persona_id=tarot.id,
                topic="draft",
                status=ReadingStatus.DRAFT.value,
                access_level=ReadingAccess.NONE.value,
                cost_units=0,
                engine_version="tarot-symbolic-v1",
                prompt_version="tarot-reader-v1",
                schema_version="reading-result-v1",
                created_at=now + timedelta(minutes=1),
            ),
            Reading(
                user_id=stranger.id,
                persona_id=tarot.id,
                topic="stranger",
                status=ReadingStatus.PREVIEW_READY.value,
                access_level=ReadingAccess.PREVIEW.value,
                cost_units=0,
                engine_version="tarot-symbolic-v1",
                prompt_version="tarot-reader-v1",
                schema_version="reading-result-v1",
                generated_at=now + timedelta(minutes=2),
                created_at=now + timedelta(minutes=2),
            ),
            Reading(
                user_id=owner.id,
                persona_id=other.id,
                topic="other_persona",
                status=ReadingStatus.PREVIEW_READY.value,
                access_level=ReadingAccess.PREVIEW.value,
                cost_units=0,
                engine_version="reflection-v1",
                prompt_version="love-oracle-v1",
                schema_version="reading-result-v1",
                generated_at=now + timedelta(minutes=3),
                created_at=now + timedelta(minutes=3),
            ),
        ]
        session.add_all((*ready_rows, *excluded))
        await session.flush()
        session.add(
            ReadingPrivateContent(
                reading_id=ready_rows[0].id,
                question_ciphertext=b"not-valid-ciphertext",
                question_format_version=999,
                context_ciphertext=b"also-invalid",
                context_format_version=999,
                result_ciphertext=b"invalid-result",
                result_format_version=999,
            )
        )

    history = ReadingHistoryService(payment_db)
    first = await history.list_ready(owner.id, "tarot_reader", page=0, page_size=2)
    second = await history.list_ready(owner.id, "tarot_reader", page=1, page_size=2)

    assert [item.topic for item in first.items] == ["decision", "work"]
    assert first.has_next and first.page == 0
    assert [item.topic for item in second.items] == ["love"]
    assert not second.has_next and second.page == 1
    assert all(
        item.status == ReadingStatus.PREVIEW_READY.value for item in (*first.items, *second.items)
    )


async def test_history_rejects_invalid_pagination_before_query(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    history = ReadingHistoryService(payment_db)
    user_id = uuid4()

    with pytest.raises(ValueError, match="non-negative"):
        await history.list_ready(user_id, "tarot_reader", page=-1)
    with pytest.raises(ValueError, match="page size"):
        await history.list_ready(user_id, "tarot_reader", page_size=21)


async def test_full_ownership_authorizes_a_result_action_only_for_the_paid_owner(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    """Feedback acts on one reading, so it must prove ownership before it is accepted."""

    now = datetime.now(UTC)
    async with payment_db.begin() as session:
        owner = User(telegram_user_id=894101, first_name="FeedbackOwner")
        stranger = User(telegram_user_id=894102, first_name="FeedbackStranger")
        persona = Persona(
            code="tarot_reader_feedback",
            display_name="Tarot Reader",
            prompt_version="tarot-reader-v1",
            schema_version="reading-result-v1",
        )
        session.add_all((owner, stranger, persona))
        await session.flush()

        def _reading(user_id: UUID) -> Reading:
            return Reading(
                user_id=user_id,
                persona_id=persona.id,
                topic="decision",
                status=ReadingStatus.PREVIEW_READY.value,
                access_level=ReadingAccess.PREVIEW.value,
                cost_units=0,
                engine_version="tarot-symbolic-v1",
                prompt_version="tarot-reader-v1",
                schema_version="reading-result-v1",
                generated_at=now,
                created_at=now,
            )

        paid = _reading(owner.id)
        preview_only = _reading(owner.id)
        removed = _reading(owner.id)
        session.add_all((paid, preview_only, removed))
        await session.flush()

        for reading in (paid, removed):
            spend = CreditTransaction(
                user_id=owner.id,
                type="spend",
                amount=-1,
                idempotency_key=f"feedback-ownership:{reading.id}",
                reading_id=reading.id,
            )
            session.add(spend)
            await session.flush()
            reading.status = ReadingStatus.FULL_READY.value
            reading.access_level = ReadingAccess.FULL.value
            reading.cost_units = 1
            reading.full_access_transaction_id = spend.id
        removed.deleted_at = now
        await session.flush()
        paid_id, preview_id, removed_id = paid.id, preview_only.id, removed.id
        owner_id, stranger_id = owner.id, stranger.id

    history = ReadingHistoryService(payment_db)

    assert await history.owns_full(owner_id, paid_id)
    assert not await history.owns_full(stranger_id, paid_id)
    assert not await history.owns_full(owner_id, preview_id)
    assert not await history.owns_full(owner_id, removed_id)
    assert not await history.owns_full(owner_id, uuid4())
