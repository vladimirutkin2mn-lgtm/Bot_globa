"""PostgreSQL financial invariants for paid oracle reading access."""

import asyncio
from typing import cast

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import CreditTransaction, User
from app.db.reading_models import Persona, Reading
from app.domain.reading import ReadingDraftRequest, ReadingSymbolInput, SymbolOrientation
from app.domain.reading_result import (
    ReadingResult,
    ReadingSafetyAssessment,
    ReadingScenario,
    ReadingSymbolResult,
    ShareCardPayload,
)
from app.services.credits_service import CreditsService
from app.services.monetized_reading import MonetizedReadingService, MonetizedReadingStatus
from app.services.reading_service import ReadingService
from app.services.sensitive_content import AESGCMSensitiveContentCipher

pytestmark = pytest.mark.postgres
PRICE = 2


def _symbols() -> list[ReadingSymbolInput]:
    return [
        ReadingSymbolInput(
            symbol_id="major_01",
            position="situation",
            orientation=SymbolOrientation.UPRIGHT,
            catalog_version="tarot-major-v1",
        ),
        ReadingSymbolInput(
            symbol_id="major_06",
            position="tension",
            orientation=SymbolOrientation.REVERSED,
            catalog_version="tarot-major-v1",
        ),
        ReadingSymbolInput(
            symbol_id="major_17",
            position="next_step",
            orientation=SymbolOrientation.UPRIGHT,
            catalog_version="tarot-major-v1",
        ),
    ]


def _result() -> ReadingResult:
    return ReadingResult(
        title="Проверка выбора",
        opening="Расклад показывает несколько способов посмотреть на решение.",
        symbols=[
            ReadingSymbolResult(
                symbol_id=symbol.symbol_id,
                position=symbol.position,
                orientation=symbol.orientation,
                interpretation=f"Интерпретация позиции {symbol.position}.",
            )
            for symbol in _symbols()
        ],
        patterns=["Спешка мешает сравнить обратимость вариантов."],
        possible_scenarios=[
            ReadingScenario(
                scenario="Пауза помогает увидеть различия.",
                conditions=["Зафиксировать критерии письменно."],
            )
        ],
        reflection_questions=["Какой риск можно обратить?"],
        practical_step="Сравнить два варианта по трём критериям.",
        uncertainty_note="Карты не определяют внешние события.",
        share_card=ShareCardPayload(
            headline="Пауза перед выбором",
            short_text="Сравните обратимость вариантов.",
        ),
        safety=ReadingSafetyAssessment(high_risk_detected=False, categories=[]),
    )


async def _ready_reading(
    sessions: async_sessionmaker[AsyncSession],
    *,
    telegram_user_id: int,
) -> tuple[User, ReadingService, Reading]:
    async with sessions.begin() as session:
        user = User(telegram_user_id=telegram_user_id, first_name="PaidReader")
        persona = Persona(
            code=f"tarot_paid_{telegram_user_id}",
            display_name="Tarot",
            prompt_version="tarot-reader-v1",
            schema_version="reading-result-v1",
        )
        session.add_all((user, persona))
        await session.flush()
    service = ReadingService(
        sessions,
        AESGCMSensitiveContentCipher(f"paid-reading-key-{telegram_user_id}"),
    )
    reading = await service.create_draft(
        user.id,
        ReadingDraftRequest(
            persona_code=persona.code,
            topic="decision",
            question="Как посмотреть на выбор?",
            context=None,
            engine_version="tarot-symbolic-v1",
            prompt_version="tarot-reader-v1",
            schema_version="reading-result-v1",
            cost_units=0,
        ),
    )
    await service.start_generation(reading.id, user.id)
    ready = await service.complete_preview(
        reading.id,
        user.id,
        cast("dict[str, object]", _result().model_dump(mode="json")),
        _symbols(),
    )
    return user, service, ready


async def test_paid_reading_unlock_is_exactly_once_under_concurrency(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user, readings, reading = await _ready_reading(payment_db, telegram_user_id=895001)
    credits = CreditsService(payment_db)
    await credits.grant(user.id, 5, "paid-reading-concurrency-grant")
    monetized = MonetizedReadingService(payment_db, credits, readings, PRICE)

    first, second = await asyncio.gather(
        monetized.unlock_full(reading.id, user.id),
        monetized.unlock_full(reading.id, user.id),
    )

    assert first.status is MonetizedReadingStatus.FULL_COMPLETED
    assert second.status is MonetizedReadingStatus.FULL_COMPLETED
    assert first.result is not None and second.result is not None
    assert await credits.balance(user.id) == 3
    async with payment_db() as session:
        stored = await session.get(Reading, reading.id)
        spend_count = await session.scalar(
            select(func.count())
            .select_from(CreditTransaction)
            .where(
                CreditTransaction.reading_id == reading.id,
                CreditTransaction.type == "spend",
            )
        )
        assert stored is not None
        assert stored.status == "full_ready"
        assert stored.access_level == "full"
        assert stored.cost_units == PRICE
        assert stored.full_access_transaction_id is not None
        assert spend_count == 1


async def test_insufficient_balance_never_changes_reading_access(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user, readings, reading = await _ready_reading(payment_db, telegram_user_id=895002)
    credits = CreditsService(payment_db)
    monetized = MonetizedReadingService(payment_db, credits, readings, PRICE)

    outcome = await monetized.unlock_full(reading.id, user.id)

    assert outcome.status is MonetizedReadingStatus.INSUFFICIENT_CREDITS
    assert outcome.balance == 0
    async with payment_db() as session:
        stored = await session.get(Reading, reading.id)
        assert stored is not None
        assert stored.status == "preview_ready"
        assert stored.access_level == "preview"
        assert stored.full_access_transaction_id is None


class FailingPromotionStore:
    def __init__(self, delegate: ReadingService) -> None:
        self._delegate = delegate

    async def load_result(self, reading_id: object, user_id: object) -> dict[str, object] | None:
        return await self._delegate.load_result(reading_id, user_id)  # type: ignore[arg-type]

    async def promote_full_access(self, *args: object, **kwargs: object) -> Reading:
        raise RuntimeError("simulated promotion failure")


async def test_technical_failure_refunds_reading_spend_exactly_once(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user, readings, reading = await _ready_reading(payment_db, telegram_user_id=895003)
    credits = CreditsService(payment_db)
    await credits.grant(user.id, PRICE, "paid-reading-refund-grant")
    monetized = MonetizedReadingService(
        payment_db,
        credits,
        FailingPromotionStore(readings),
        PRICE,
    )

    first = await monetized.unlock_full(reading.id, user.id)
    second = await monetized.unlock_full(reading.id, user.id)

    assert first.status is MonetizedReadingStatus.TECHNICAL_FAILURE_REFUNDED
    assert second.status is MonetizedReadingStatus.NOT_FOUND
    assert await credits.balance(user.id) == PRICE
    async with payment_db() as session:
        spend = await session.scalar(
            select(CreditTransaction).where(
                CreditTransaction.reading_id == reading.id,
                CreditTransaction.type == "spend",
            )
        )
        assert spend is not None
        refunds = await session.scalar(
            select(func.count())
            .select_from(CreditTransaction)
            .where(CreditTransaction.reverses_transaction_id == spend.id)
        )
        assert refunds == 1
