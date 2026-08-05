from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text()
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"patch anchor not found: {relative}: {old[:80]!r}")
    path.write_text(text.replace(old, new, 1))


def main() -> None:
    replace_once(
        "heartsignal/app/db/models.py",
        '''        CheckConstraint(
            "type <> 'spend' OR analysis_id IS NOT NULL",
            name="ck_credit_transactions_spend_analysis",
        ),''',
        '''        CheckConstraint(
            "type <> 'spend' OR ((analysis_id IS NOT NULL AND reading_id IS NULL) OR "
            "(analysis_id IS NULL AND reading_id IS NOT NULL))",
            name="ck_credit_transactions_spend_target",
        ),''',
    )
    replace_once(
        "heartsignal/app/db/models.py",
        '''    analysis_id: Mapped[UUID | None] = mapped_column(ForeignKey("analyses.id", ondelete="RESTRICT"))
    payment_order_id: Mapped[UUID | None] = mapped_column(''',
        '''    analysis_id: Mapped[UUID | None] = mapped_column(ForeignKey("analyses.id", ondelete="RESTRICT"))
    reading_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("readings.id", ondelete="RESTRICT"), index=True
    )
    payment_order_id: Mapped[UUID | None] = mapped_column(''',
    )

    replace_once(
        "heartsignal/app/db/reading_models.py",
        '''        CheckConstraint("cost_units >= 0", name="ck_readings_cost_units"),
        CheckConstraint(
            "(status IN ('draft','generating','failed','deleted') AND access_level = 'none') OR "''',
        '''        CheckConstraint("cost_units >= 0", name="ck_readings_cost_units"),
        CheckConstraint(
            "(status = 'full_ready' AND access_level = 'full' AND cost_units > 0 "
            "AND full_access_transaction_id IS NOT NULL) OR "
            "(status = 'deleted' AND access_level = 'none' AND "
            "((cost_units = 0 AND full_access_transaction_id IS NULL) OR "
            "(cost_units > 0 AND full_access_transaction_id IS NOT NULL))) OR "
            "(status NOT IN ('full_ready','deleted') AND cost_units = 0 "
            "AND full_access_transaction_id IS NULL)",
            name="ck_readings_paid_access",
        ),
        CheckConstraint(
            "(status IN ('draft','generating','failed','deleted') AND access_level = 'none') OR "''',
    )
    replace_once(
        "heartsignal/app/db/reading_models.py",
        '''    cost_units: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    engine_version: Mapped[str] = mapped_column(String(64))''',
        '''    cost_units: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    full_access_transaction_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "credit_transactions.id",
            ondelete="RESTRICT",
            use_alter=True,
            name="fk_readings_full_transaction",
        ),
        nullable=True,
    )
    engine_version: Mapped[str] = mapped_column(String(64))''',
    )

    replace_once(
        "heartsignal/app/services/credits_service.py",
        '''from app.db.models import Analysis, CreditReservation, CreditTransaction, User
''',
        '''from app.db.models import Analysis, CreditReservation, CreditTransaction, User
from app.db.reading_models import Reading
''',
    )
    replace_once(
        "heartsignal/app/services/credits_service.py",
        '''    ANALYSIS_NOT_FOUND = "analysis_not_found"
    INVALID_AMOUNT = "invalid_amount"
''',
        '''    ANALYSIS_NOT_FOUND = "analysis_not_found"
    READING_NOT_FOUND = "reading_not_found"
    INVALID_AMOUNT = "invalid_amount"
''',
    )
    replace_once(
        "heartsignal/app/services/credits_service.py",
        '''    async def refund(self, user_id: UUID, analysis_id: UUID, spend_id: UUID) -> RefundOutcome:
''',
        '''    async def spend_reading(
        self,
        user_id: UUID,
        reading_id: UUID,
        amount: int,
    ) -> SpendResult:
        if amount < 1:
            return SpendResult(SpendOutcome.INVALID_AMOUNT)
        key = f"reading_full_access:{reading_id}"
        async with self._sessions.begin() as session:
            user = await session.scalar(
                select(User)
                .where(User.id == user_id, User.privacy_status == "active")
                .with_for_update()
            )
            if user is None:
                return SpendResult(SpendOutcome.READING_NOT_FOUND)
            reading = await session.scalar(
                select(Reading).where(
                    Reading.id == reading_id,
                    Reading.user_id == user_id,
                    Reading.status.in_(("preview_ready", "full_ready")),
                )
            )
            if reading is None:
                return SpendResult(SpendOutcome.READING_NOT_FOUND)
            existing = await session.scalar(
                select(CreditTransaction).where(CreditTransaction.idempotency_key == key)
            )
            balance = int(
                await session.scalar(
                    select(func.coalesce(func.sum(CreditTransaction.amount), 0)).where(
                        CreditTransaction.user_id == user_id
                    )
                )
                or 0
            )
            if existing is not None:
                if not (
                    existing.user_id == user_id
                    and existing.reading_id == reading_id
                    and existing.analysis_id is None
                    and existing.type == "spend"
                    and existing.amount == -amount
                ):
                    return SpendResult(SpendOutcome.READING_NOT_FOUND, balance=balance)
                refunded = await session.scalar(
                    select(CreditTransaction.id).where(
                        CreditTransaction.reverses_transaction_id == existing.id
                    )
                )
                if refunded is not None:
                    return SpendResult(SpendOutcome.ALREADY_SPENT_REFUNDED, balance=balance)
                return SpendResult(SpendOutcome.ALREADY_SPENT_ACTIVE, existing.id, balance)
            reserved = int(
                await session.scalar(
                    select(func.coalesce(func.sum(CreditReservation.credit_units), 0)).where(
                        CreditReservation.user_id == user_id,
                        CreditReservation.status == "active",
                    )
                )
                or 0
            )
            available = max(0, balance - reserved)
            if available < amount:
                return SpendResult(SpendOutcome.INSUFFICIENT_BALANCE, balance=available)
            row = CreditTransaction(
                user_id=user_id,
                type="spend",
                amount=-amount,
                idempotency_key=key,
                reading_id=reading_id,
            )
            session.add(row)
            await session.flush()
            return SpendResult(SpendOutcome.SPENT, row.id, available - amount)

    async def refund_reading_if_not_full(
        self,
        user_id: UUID,
        reading_id: UUID,
        spend_id: UUID,
        expected_cost: int,
    ) -> RefundOutcome:
        async with self._sessions.begin() as session:
            reading = await session.scalar(
                select(Reading)
                .where(Reading.id == reading_id, Reading.user_id == user_id)
                .with_for_update()
            )
            if reading is None:
                return RefundOutcome.AUTHORIZATION_MISMATCH
            spend = await session.scalar(
                select(CreditTransaction).where(CreditTransaction.id == spend_id).with_for_update()
            )
            if spend is None:
                return RefundOutcome.SPEND_NOT_FOUND
            if spend.user_id != user_id or spend.reading_id != reading_id:
                return RefundOutcome.AUTHORIZATION_MISMATCH
            if spend.analysis_id is not None or spend.type != "spend" or spend.amount != -expected_cost:
                return RefundOutcome.INVALID_SPEND
            if (
                reading.full_access_transaction_id == spend_id
                and reading.cost_units == expected_cost
            ):
                return RefundOutcome.ACCESS_ALREADY_GRANTED
            existing = await session.scalar(
                select(CreditTransaction.id).where(
                    CreditTransaction.reverses_transaction_id == spend.id
                )
            )
            if existing is not None:
                return RefundOutcome.ALREADY_REFUNDED
            session.add(
                CreditTransaction(
                    user_id=user_id,
                    type="refund",
                    amount=-spend.amount,
                    idempotency_key=f"refund:{spend.id}",
                    reading_id=reading_id,
                    reverses_transaction_id=spend.id,
                )
            )
            return RefundOutcome.REFUNDED

    async def refund(self, user_id: UUID, analysis_id: UUID, spend_id: UUID) -> RefundOutcome:
''',
    )

    replace_once(
        "heartsignal/app/repositories/readings.py",
        '''from app.db.models import User
''',
        '''from app.db.models import CreditTransaction, User
''',
    )
    replace_once(
        "heartsignal/app/repositories/readings.py",
        '''        reading = await self._required_locked(reading_id, user_id)
        target = ReadingStatus.FULL_READY if full else ReadingStatus.PREVIEW_READY
        ensure_reading_transition(ReadingStatus(reading.status), target)
''',
        '''        if full:
            raise ValueError("direct full generation requires paid promotion")
        reading = await self._required_locked(reading_id, user_id)
        target = ReadingStatus.PREVIEW_READY
        ensure_reading_transition(ReadingStatus(reading.status), target)
''',
    )
    replace_once(
        "heartsignal/app/repositories/readings.py",
        '''        reading.status = target.value
        reading.access_level = ReadingAccess.FULL.value if full else ReadingAccess.PREVIEW.value
        reading.generated_at = datetime.now(UTC)
''',
        '''        reading.status = target.value
        reading.access_level = ReadingAccess.PREVIEW.value
        reading.generated_at = datetime.now(UTC)
''',
    )
    replace_once(
        "heartsignal/app/repositories/readings.py",
        '''    async def promote_full_access(self, reading_id: UUID, user_id: UUID) -> Reading:
        reading = await self._required_locked(reading_id, user_id)
        ensure_reading_transition(ReadingStatus(reading.status), ReadingStatus.FULL_READY)
        private = await self._private_row(reading.id)
        if private.result_ciphertext is None:
            raise RuntimeError("reading result is unavailable")
        reading.status = ReadingStatus.FULL_READY.value
        reading.access_level = ReadingAccess.FULL.value
        await self._session.flush()
        return reading
''',
        '''    async def promote_full_access(
        self,
        reading_id: UUID,
        user_id: UUID,
        cost_units: int,
        transaction_id: UUID,
    ) -> Reading:
        if cost_units < 1:
            raise ValueError("paid reading cost must be positive")
        reading = await self._required_locked(reading_id, user_id)
        private = await self._private_row(reading.id)
        if private.result_ciphertext is None:
            raise RuntimeError("reading result is unavailable")
        spend = await self._session.scalar(
            select(CreditTransaction)
            .where(CreditTransaction.id == transaction_id)
            .with_for_update()
        )
        if (
            spend is None
            or spend.user_id != user_id
            or spend.reading_id != reading_id
            or spend.analysis_id is not None
            or spend.type != "spend"
            or spend.amount != -cost_units
        ):
            raise ValueError("reading spend transaction mismatch")
        refunded = await self._session.scalar(
            select(CreditTransaction.id)
            .where(CreditTransaction.reverses_transaction_id == spend.id)
            .with_for_update()
        )
        if refunded is not None:
            raise ValueError("reading spend was refunded")
        if ReadingStatus(reading.status) is ReadingStatus.FULL_READY:
            if (
                reading.full_access_transaction_id == transaction_id
                and reading.cost_units == cost_units
                and reading.access_level == ReadingAccess.FULL.value
            ):
                return reading
            raise ValueError("reading full access transaction mismatch")
        ensure_reading_transition(ReadingStatus(reading.status), ReadingStatus.FULL_READY)
        reading.status = ReadingStatus.FULL_READY.value
        reading.access_level = ReadingAccess.FULL.value
        reading.cost_units = cost_units
        reading.full_access_transaction_id = transaction_id
        await self._session.flush()
        return reading
''',
    )

    replace_once(
        "heartsignal/app/services/reading_service.py",
        '''    async def complete_full(
        self,
        reading_id: UUID,
        user_id: UUID,
        result: dict[str, object],
        symbols: list[ReadingSymbolInput],
    ) -> Reading:
        async with self._sessions.begin() as session:
            return await self._repository(session).complete_generation(
                reading_id,
                user_id,
                result,
                symbols,
                full=True,
            )

    async def promote_full_access(self, reading_id: UUID, user_id: UUID) -> Reading:
        async with self._sessions.begin() as session:
            return await self._repository(session).promote_full_access(reading_id, user_id)
''',
        '''    async def complete_full(
        self,
        reading_id: UUID,
        user_id: UUID,
        result: dict[str, object],
        symbols: list[ReadingSymbolInput],
        cost_units: int,
        transaction_id: UUID,
    ) -> Reading:
        await self.complete_preview(reading_id, user_id, result, symbols)
        return await self.promote_full_access(
            reading_id,
            user_id,
            cost_units,
            transaction_id,
        )

    async def promote_full_access(
        self,
        reading_id: UUID,
        user_id: UUID,
        cost_units: int,
        transaction_id: UUID,
    ) -> Reading:
        async with self._sessions.begin() as session:
            return await self._repository(session).promote_full_access(
                reading_id,
                user_id,
                cost_units,
                transaction_id,
            )
''',
    )

    replace_once(
        "heartsignal/app/config.py",
        '''    analysis_price_credits: int = Field(default=1, ge=1)
    payment_provider: str = "mock"
''',
        '''    analysis_price_credits: int = Field(default=1, ge=1)
    tarot_full_price_credits: int = Field(default=1, ge=1)
    payment_provider: str = "mock"
''',
    )

    replace_once(
        "heartsignal/app/bot/main.py",
        '''from app.services.checkout_service import CheckoutService
from app.services.persona_registry import PersonaRegistryService
''',
        '''from app.services.checkout_service import CheckoutService
from app.services.credits_service import CreditsService
from app.services.monetized_reading import MonetizedReadingService
from app.services.persona_registry import PersonaRegistryService
''',
    )
    replace_once(
        "heartsignal/app/bot/main.py",
        '''    dispatcher["persona_registry"] = PersonaRegistryService(sessions)
    dispatcher["tarot_history"] = ReadingHistoryService(sessions)
    dispatcher["tarot_use_case"] = TarotReadingUseCase.from_services(
        ReadingService(sessions, cipher, settings.raw_content_retention_days),
''',
        '''    dispatcher["persona_registry"] = PersonaRegistryService(sessions)
    dispatcher["tarot_history"] = ReadingHistoryService(sessions)
    reading_service = ReadingService(sessions, cipher, settings.raw_content_retention_days)
    dispatcher["tarot_use_case"] = TarotReadingUseCase.from_services(
        reading_service,
''',
    )
    replace_once(
        "heartsignal/app/bot/main.py",
        '''    )
    dispatcher.startup.register(sync_persona_registry)
''',
        '''    )
    dispatcher["tarot_monetized"] = MonetizedReadingService(
        sessions,
        CreditsService(sessions),
        reading_service,
        settings.tarot_full_price_credits,
    )
    dispatcher.startup.register(sync_persona_registry)
''',
    )

    replace_once(
        "heartsignal/app/bot/tarot_keyboards.py",
        '''def tarot_result_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Новый расклад", callback_data="tarot:new")],
            [InlineKeyboardButton(text="Мои расклады", callback_data="tarot:history")],
            [InlineKeyboardButton(text="Главное меню", callback_data="tarot:menu")],
        ]
    )
''',
        '''def tarot_result_keyboard(
    reading_id: UUID | None = None,
    price_credits: int | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if reading_id is not None and price_credits is not None:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"Открыть полный расклад за {price_credits} кр.",
                    callback_data=f"tarot:unlock:{reading_id}",
                )
            ]
        )
    rows.extend(
        [
            [InlineKeyboardButton(text="Новый расклад", callback_data="tarot:new")],
            [InlineKeyboardButton(text="Мои расклады", callback_data="tarot:history")],
            [InlineKeyboardButton(text="Главное меню", callback_data="tarot:menu")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tarot_full_result_keyboard() -> InlineKeyboardMarkup:
    return tarot_result_keyboard()


def tarot_insufficient_keyboard(reading_id: UUID) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Купить кредиты", callback_data="menu:balance")],
            [
                InlineKeyboardButton(
                    text="Проверить баланс и открыть",
                    callback_data=f"tarot:unlock:{reading_id}",
                )
            ],
            [InlineKeyboardButton(text="Мои расклады", callback_data="tarot:history")],
            [InlineKeyboardButton(text="Главное меню", callback_data="tarot:menu")],
        ]
    )
''',
    )

    replace_once(
        "heartsignal/app/bot/tarot_handlers.py",
        '''from app.bot.keyboards import main_menu_keyboard
from app.bot.states import TarotStates
''',
        '''from app.bot.keyboards import main_menu_keyboard
from app.bot.states import TarotStates
from app.bot.tarot_full_renderer import TarotFullRenderer
''',
    )
    replace_once(
        "heartsignal/app/bot/tarot_handlers.py",
        '''    tarot_context_keyboard,
    tarot_history_keyboard,
    tarot_result_keyboard,
''',
        '''    tarot_context_keyboard,
    tarot_full_result_keyboard,
    tarot_history_keyboard,
    tarot_insufficient_keyboard,
    tarot_result_keyboard,
''',
    )
    replace_once(
        "heartsignal/app/bot/tarot_handlers.py",
        '''from app.services.onboarding import OnboardingService
from app.services.reading_generation import ReadingGenerationStatus
''',
        '''from app.services.monetized_reading import MonetizedReadingService, MonetizedReadingStatus
from app.services.onboarding import OnboardingService
from app.services.reading_generation import ReadingGenerationStatus
''',
    )
    replace_once(
        "heartsignal/app/bot/tarot_handlers.py",
        '''renderer = TarotPreviewRenderer()
''',
        '''renderer = TarotPreviewRenderer()
full_renderer = TarotFullRenderer()
''',
    )
    replace_once(
        "heartsignal/app/bot/tarot_handlers.py",
        '''HISTORY_EMPTY = "Готовых раскладов пока нет."
''',
        '''HISTORY_EMPTY = "Готовых раскладов пока нет."
UNLOCKING = "Проверяю баланс и открываю полный расклад…"
INSUFFICIENT = "Для полного расклада нужно {price} кр. Доступный баланс: {balance} кр."
UNLOCK_FAILED = "Не удалось открыть полный расклад. Списание отменено или возвращено."
''',
    )
    replace_once(
        "heartsignal/app/bot/tarot_handlers.py",
        '''    tarot_use_case: TarotReadingUseCase,
) -> None:
''',
        '''    tarot_use_case: TarotReadingUseCase,
    tarot_monetized: MonetizedReadingService,
) -> None:
''',
    )
    replace_once(
        "heartsignal/app/bot/tarot_handlers.py",
        '''    outcome = await tarot_use_case.generate_existing_preview(reading_id, user.id)
    await _deliver(callback.message, state, outcome)
''',
        '''    outcome = await tarot_use_case.generate_existing_preview(reading_id, user.id)
    await _deliver(callback.message, state, outcome, tarot_monetized)
''',
    )
    replace_once(
        "heartsignal/app/bot/tarot_handlers.py",
        '''    tarot_use_case: TarotReadingUseCase,
) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        await _generate_new(
''',
        '''    tarot_use_case: TarotReadingUseCase,
    tarot_monetized: MonetizedReadingService,
) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        await _generate_new(
''',
    )
    replace_once(
        "heartsignal/app/bot/tarot_handlers.py",
        '''            tarot_use_case,
            context=None,
''',
        '''            tarot_use_case,
            tarot_monetized,
            context=None,
''',
    )
    replace_once(
        "heartsignal/app/bot/tarot_handlers.py",
        '''    tarot_use_case: TarotReadingUseCase,
) -> None:
    if message.from_user is None:
''',
        '''    tarot_use_case: TarotReadingUseCase,
    tarot_monetized: MonetizedReadingService,
) -> None:
    if message.from_user is None:
''',
    )
    replace_once(
        "heartsignal/app/bot/tarot_handlers.py",
        '''        tarot_use_case,
        context=context,
''',
        '''        tarot_use_case,
        tarot_monetized,
        context=context,
''',
    )
    replace_once(
        "heartsignal/app/bot/tarot_handlers.py",
        '''    tarot_use_case: TarotReadingUseCase,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
''',
        '''    tarot_use_case: TarotReadingUseCase,
    tarot_monetized: MonetizedReadingService,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
''',
    )
    replace_once(
        "heartsignal/app/bot/tarot_handlers.py",
        '''    outcome = await tarot_use_case.generate_existing_preview(reading_id, user.id)
    await _deliver(callback.message, state, outcome)


@router.message(TarotStates.generating)
''',
        '''    outcome = await tarot_use_case.generate_existing_preview(reading_id, user.id)
    await _deliver(callback.message, state, outcome, tarot_monetized)


@router.callback_query(F.data.startswith("tarot:unlock:"))
async def unlock_tarot(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    tarot_use_case: TarotReadingUseCase,
    tarot_monetized: MonetizedReadingService,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    user = await onboarding.current_user(callback.from_user.id)
    if user is None:
        await state.clear()
        await callback.message.answer(NOT_ONBOARDED)
        return
    try:
        reading_id = UUID((callback.data or "").removeprefix("tarot:unlock:"))
    except ValueError:
        await callback.message.answer(UNAVAILABLE, reply_markup=tarot_result_keyboard())
        return
    await callback.message.answer(UNLOCKING)
    unlocked = await tarot_monetized.unlock_full(reading_id, user.id)
    if unlocked.status is MonetizedReadingStatus.INSUFFICIENT_CREDITS:
        await callback.message.answer(
            INSUFFICIENT.format(
                price=tarot_monetized.price_credits,
                balance=unlocked.balance or 0,
            ),
            reply_markup=tarot_insufficient_keyboard(reading_id),
        )
        return
    if unlocked.status is MonetizedReadingStatus.FULL_COMPLETED:
        outcome = await tarot_use_case.generate_existing_preview(reading_id, user.id)
        if (
            outcome.generation.status is ReadingGenerationStatus.COMPLETED
            and outcome.generation.result is not None
        ):
            rendered = full_renderer.render(outcome)
            for index, chunk in enumerate(rendered.chunks):
                markup = (
                    tarot_full_result_keyboard()
                    if index == len(rendered.chunks) - 1
                    else None
                )
                await callback.message.answer(chunk, reply_markup=markup)
            return
    await callback.message.answer(UNLOCK_FAILED, reply_markup=tarot_result_keyboard())


@router.message(TarotStates.generating)
''',
    )
    replace_once(
        "heartsignal/app/bot/tarot_handlers.py",
        '''    tarot_use_case: TarotReadingUseCase,
    *,
    context: str | None,
''',
        '''    tarot_use_case: TarotReadingUseCase,
    tarot_monetized: MonetizedReadingService,
    *,
    context: str | None,
''',
    )
    replace_once(
        "heartsignal/app/bot/tarot_handlers.py",
        '''    await _deliver(message, state, outcome)


async def _deliver(
    message: Message,
    state: FSMContext,
    outcome: TarotPreviewOutcome,
) -> None:
''',
        '''    await _deliver(message, state, outcome, tarot_monetized)


async def _deliver(
    message: Message,
    state: FSMContext,
    outcome: TarotPreviewOutcome,
    monetized: MonetizedReadingService,
) -> None:
''',
    )
    replace_once(
        "heartsignal/app/bot/tarot_handlers.py",
        '''            markup = tarot_result_keyboard() if index == len(rendered.chunks) - 1 else None
''',
        '''            markup = (
                tarot_result_keyboard(outcome.reading_id, monetized.price_credits)
                if index == len(rendered.chunks) - 1
                else None
            )
''',
    )

    replace_once(
        "heartsignal/tests/test_reading_service_postgres.py",
        '''    full = await service.promote_full_access(reading.id, owner.id)
    assert full.status == ReadingStatus.FULL_READY.value
    assert full.access_level == "full"
    assert await service.load_result(reading.id, owner.id) == result
''',
        '''    credits = CreditsService(payment_db)
    await credits.grant(owner.id, 1, "reading-service-paid-grant")
    spent = await credits.spend_reading(owner.id, reading.id, 1)
    assert spent.transaction_id is not None
    full = await service.promote_full_access(reading.id, owner.id, 1, spent.transaction_id)
    assert full.status == ReadingStatus.FULL_READY.value
    assert full.access_level == "full"
    assert full.cost_units == 1
    assert full.full_access_transaction_id == spent.transaction_id
    assert await service.load_result(reading.id, owner.id) == result
''',
    )
    replace_once(
        "heartsignal/tests/test_reading_service_postgres.py",
        '''from app.services.reading_service import PersonaUnavailableError, ReadingService
''',
        '''from app.services.credits_service import CreditsService
from app.services.reading_service import PersonaUnavailableError, ReadingService
''',
    )
    replace_once(
        "heartsignal/tests/test_reading_service_postgres.py",
        '''    ready = await service.complete_full(
        reading.id,
        owner.id,
        {"title": "Retry succeeded"},
        _symbols(),
    )
    assert ready.status == ReadingStatus.FULL_READY.value
''',
        '''    ready = await service.complete_preview(
        reading.id,
        owner.id,
        {"title": "Retry succeeded"},
        _symbols(),
    )
    assert ready.status == ReadingStatus.PREVIEW_READY.value
''',
    )
    replace_once(
        "heartsignal/tests/test_reading_service_postgres.py",
        '''        cost_units=1,
''',
        '''        cost_units=0,
''',
    )

    replace_once(
        "heartsignal/tests/test_schema_health.py",
        '''    assert expected_schema_heads() == ("20260805_17",)
''',
        '''    assert expected_schema_heads() == ("20260805_18",)
''',
    )
    replace_once(
        "heartsignal/scripts/run_platform_invariants.sh",
        '''  tests/test_account_deletion_postgres.py::test_complete_account_tombstone_preserves_immutable_ledger \\
  "$@"
''',
        '''  tests/test_account_deletion_postgres.py::test_complete_account_tombstone_preserves_immutable_ledger \\
  tests/test_monetized_reading_postgres.py::test_paid_reading_unlock_is_exactly_once_under_concurrency \\
  tests/test_monetized_reading_postgres.py::test_technical_failure_refunds_reading_spend_exactly_once \\
  "$@"
''',
    )

    replace_once(
        "heartsignal/tests/test_tarot_telegram.py",
        '''    tarot_context_keyboard,
    tarot_result_keyboard,
''',
        '''    tarot_context_keyboard,
    tarot_insufficient_keyboard,
    tarot_result_keyboard,
''',
    )
    replace_once(
        "heartsignal/tests/test_tarot_telegram.py",
        '''        tarot_result_keyboard(),
        tarot_retry_keyboard(reading_id),
''',
        '''        tarot_result_keyboard(reading_id, 2),
        tarot_insufficient_keyboard(reading_id),
        tarot_retry_keyboard(reading_id),
''',
    )
    replace_once(
        "heartsignal/tests/test_tarot_telegram.py",
        '''    assert f"tarot:retry:{reading_id}" in callbacks
''',
        '''    assert f"tarot:retry:{reading_id}" in callbacks
    assert f"tarot:unlock:{reading_id}" in callbacks
''',
    )

    # The one-shot patcher removes itself and its workflow from the feature branch.
    (ROOT / ".github/scripts/apply_paid_tarot_patch.py").unlink()
    (ROOT / ".github/workflows/apply-paid-tarot-patch.yml").unlink()


if __name__ == "__main__":
    main()
