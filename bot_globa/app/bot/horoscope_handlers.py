"""Telegram FSM for the astrologer: consented birth-profile intake, then the reading.

This is the one persona whose intake collects sensitive data, so every step is explicit:
consent before any birth field is asked, the place query is the only value that leaves
the service, and nothing here logs a date, a place or coordinates.
"""

import logging
from datetime import UTC, date, datetime, time
from typing import Any
from uuid import UUID

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app.bot import horoscope_flow as flow
from app.bot import texts
from app.bot.consent import ensure_consent
from app.bot.horoscope_flow import HOROSCOPE_FLOW
from app.bot.horoscope_renderer import HoroscopeRenderer
from app.bot.keyboards import main_menu_keyboard, products_keyboard
from app.bot.memory_keyboards import memory_disabled_keyboard
from app.bot.persona_flow import (
    CONTEXT_LIMIT,
    INVALID_TEXT,
    NOT_ONBOARDED,
    QUESTION_EXAMPLE,
    QUESTION_LIMIT,
    QUESTION_PROMPT,
    UNLOCKING,
)
from app.bot.scene_media import Scene
from app.bot.screen import send_artifact, show_screen
from app.bot.states import HoroscopeStates
from app.config import Settings
from app.domain.billing import BillingCatalog
from app.domain.birth_profile import BirthProfileConsentStatus
from app.domain.horoscope import HoroscopeScope
from app.providers.analytics import OracleProductEvent
from app.providers.geocoding.base import GeocodedPlace, GeocodingError
from app.services.birth_place_lookup import (
    AmbiguousBirthTimeError,
    BirthPlaceLookupService,
    InvalidBirthPlaceQueryError,
    UnresolvableBirthPlaceError,
)
from app.services.birth_profile import BirthProfileConsentRequiredError, BirthProfileService
from app.services.horoscope_generation import HoroscopeGenerationStatus
from app.services.horoscope_reading import HoroscopePreviewOutcome, HoroscopePreviewRequest
from app.services.horoscope_reading import HoroscopeReadingUseCase as UseCase
from app.services.monetized_reading import MonetizedReadingService, MonetizedReadingStatus
from app.services.onboarding import OnboardingService, TelegramIdentity
from app.services.oracle_memory import OracleMemoryService
from app.services.oracle_product_analytics import OracleProductAnalytics
from app.services.preview_entitlement import ReadingPreviewVisibility
from app.services.reading_history import ReadingHistoryService

logger = logging.getLogger(__name__)

DATE_FORMAT = "%d.%m.%Y"
TIME_FORMAT = "%H:%M"


def create_horoscope_router() -> Router:
    """Register the astrologer flow under its own namespace."""
    handlers = HoroscopeHandlers()
    router = Router(name=HOROSCOPE_FLOW.namespace)

    router.message.register(handlers.start_from_command, Command(HOROSCOPE_FLOW.namespace))
    router.message.register(
        handlers.start_from_command,
        CommandStart(deep_link=True, magic=F.args == HOROSCOPE_FLOW.namespace),
    )
    router.message.register(handlers.receive_birth_date, HoroscopeStates.waiting_for_birth_date)
    router.message.register(handlers.receive_birth_place, HoroscopeStates.waiting_for_birth_place)
    router.message.register(handlers.receive_birth_time, HoroscopeStates.waiting_for_birth_time)
    router.message.register(handlers.receive_question, HoroscopeStates.waiting_for_question)
    router.message.register(handlers.receive_context, HoroscopeStates.waiting_for_context)
    router.message.register(handlers.already_generating, HoroscopeStates.generating)

    callbacks = router.callback_query
    callbacks.register(handlers.start_from_menu, F.data == f"menu:{HOROSCOPE_FLOW.namespace}")
    callbacks.register(
        handlers.accept_onboarding_consent,
        F.data == f"onboarding:consent:{HOROSCOPE_FLOW.namespace}",
    )
    callbacks.register(handlers.restart, F.data == flow.callback("new"))
    callbacks.register(handlers.cancel, F.data == flow.callback("cancel"))
    callbacks.register(handlers.to_main_menu, F.data == flow.callback("menu"))
    callbacks.register(handlers.grant_consent, F.data == flow.callback("consent", "grant"))
    callbacks.register(handlers.decline_consent, F.data == flow.callback("consent", "decline"))
    callbacks.register(handlers.retry_place, F.data == flow.callback("place", "retry"))
    callbacks.register(
        handlers.choose_place,
        F.data.startswith(flow.callback("place", "pick", "")),
    )
    callbacks.register(handlers.skip_birth_time, F.data == flow.callback("time", "unknown"))
    callbacks.register(
        handlers.choose_offset,
        F.data.startswith(flow.callback("offset", "pick", "")),
    )
    callbacks.register(handlers.show_profile, F.data == flow.callback("profile"))
    callbacks.register(handlers.edit_profile, F.data == flow.callback("profile", "edit"))
    callbacks.register(handlers.delete_profile, F.data == flow.callback("profile", "delete"))
    callbacks.register(handlers.show_history, F.data == flow.callback("history"))
    callbacks.register(
        handlers.show_history_page,
        F.data.startswith(flow.callback("history", "page", "")),
    )
    callbacks.register(
        handlers.open_from_history,
        F.data.startswith(flow.callback("history", "open", "")),
    )
    callbacks.register(handlers.select_topic, F.data.startswith(flow.callback("topic", "")))
    callbacks.register(
        handlers.show_example,
        HoroscopeStates.waiting_for_question,
        F.data == flow.callback("example"),
    )
    callbacks.register(
        handlers.skip_context,
        HoroscopeStates.waiting_for_context,
        F.data == flow.callback("context", "skip"),
    )
    callbacks.register(handlers.retry, F.data.startswith(flow.callback("retry", "")))
    callbacks.register(handlers.unlock, F.data.startswith(flow.callback("unlock", "")))
    return router


class HoroscopeHandlers:
    """Every astrologer handler; the birth intake runs before the reading intake."""

    # ------------------------------------------------------------------ entry ---

    async def start_from_command(
        self,
        message: Message,
        state: FSMContext,
        onboarding: OnboardingService,
        birth_profile_service: BirthProfileService,
        privacy_retention_days: int,
    ) -> None:
        if message.from_user is None:
            return
        await self._start(
            message,
            message.from_user.id,
            state,
            onboarding,
            birth_profile_service,
            TelegramIdentity(
                telegram_user_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                language=message.from_user.language_code,
            ),
            privacy_retention_days,
        )

    async def start_from_menu(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        onboarding: OnboardingService,
        birth_profile_service: BirthProfileService,
        privacy_retention_days: int,
    ) -> None:
        await callback.answer()
        if isinstance(callback.message, Message):
            await self._start(
                callback.message,
                callback.from_user.id,
                state,
                onboarding,
                birth_profile_service,
                TelegramIdentity(
                    telegram_user_id=callback.from_user.id,
                    username=callback.from_user.username,
                    first_name=callback.from_user.first_name,
                    language=callback.from_user.language_code,
                ),
                privacy_retention_days,
            )

    async def accept_onboarding_consent(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        onboarding: OnboardingService,
        birth_profile_service: BirthProfileService,
        privacy_retention_days: int,
    ) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        identity = TelegramIdentity(
            telegram_user_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
            language=callback.from_user.language_code,
        )
        if await onboarding.current_user(callback.from_user.id) is None:
            await onboarding.start(identity)
        await onboarding.accept_consent(callback.from_user.id)
        await self._start(
            callback.message,
            callback.from_user.id,
            state,
            onboarding,
            birth_profile_service,
            identity,
            privacy_retention_days,
        )

    async def restart(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        onboarding: OnboardingService,
        birth_profile_service: BirthProfileService,
        privacy_retention_days: int,
    ) -> None:
        await self.start_from_menu(
            callback,
            state,
            onboarding,
            birth_profile_service,
            privacy_retention_days,
        )

    async def cancel(self, callback: CallbackQuery, state: FSMContext) -> None:
        """Abandon the intake outright; consent stays granted so a retry is one step."""
        await self.to_main_menu(callback, state)

    async def to_main_menu(self, callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        await state.clear()
        if isinstance(callback.message, Message):
            await show_screen(
                callback.message,
                Scene.MAIN_MENU,
                texts.MAIN_MENU,
                reply_markup=main_menu_keyboard(),
                state=state,
            )

    # ---------------------------------------------------------------- consent ---

    async def grant_consent(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        onboarding: OnboardingService,
        birth_profile_service: BirthProfileService,
        privacy_retention_days: int,
    ) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        if not await ensure_consent(
            callback.message,
            callback.from_user.id,
            state,
            onboarding,
            privacy_retention_days,
            destination=HOROSCOPE_FLOW.namespace,
        ):
            return
        user = await onboarding.current_user(callback.from_user.id)
        if user is None:
            await state.clear()
            await callback.message.answer(NOT_ONBOARDED)
            return
        await birth_profile_service.grant_consent(user.id)
        await self._ask_birth_date(callback.message, state)

    async def decline_consent(self, callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        await state.clear()
        if isinstance(callback.message, Message):
            await show_screen(
                callback.message,
                Scene.ASTRO_CONSENT_DECLINED,
                flow.CONSENT_DECLINED,
                reply_markup=main_menu_keyboard(),
                state=state,
            )

    # ------------------------------------------------------------ birth intake ---

    async def receive_birth_date(
        self,
        message: Message,
        state: FSMContext,
        onboarding: OnboardingService,
        privacy_retention_days: int,
    ) -> None:
        if message.from_user is None:
            return
        if not await ensure_consent(
            message,
            message.from_user.id,
            state,
            onboarding,
            privacy_retention_days,
            destination=HOROSCOPE_FLOW.namespace,
        ):
            return
        parsed = _parse_date(message.text)
        if parsed is None:
            await show_screen(
                message,
                Scene.ASTRO_BIRTH_DATE_ERROR,
                flow.BIRTH_DATE_INVALID,
                reply_markup=flow.cancel_keyboard(),
                state=state,
            )
            return
        await state.update_data(birth_date=parsed.isoformat())
        await state.set_state(HoroscopeStates.waiting_for_birth_place)
        await show_screen(
            message,
            Scene.ASTRO_BIRTH_PLACE,
            flow.BIRTH_PLACE_PROMPT,
            reply_markup=flow.cancel_keyboard(),
            state=state,
        )

    async def receive_birth_place(
        self,
        message: Message,
        state: FSMContext,
        birth_place_lookup: BirthPlaceLookupService,
        onboarding: OnboardingService,
        privacy_retention_days: int,
    ) -> None:
        if message.from_user is None:
            return
        if not await ensure_consent(
            message,
            message.from_user.id,
            state,
            onboarding,
            privacy_retention_days,
            destination=HOROSCOPE_FLOW.namespace,
        ):
            return
        query = (message.text or "").strip()
        try:
            places = await birth_place_lookup.search(query)
        except InvalidBirthPlaceQueryError:
            await show_screen(
                message,
                Scene.ASTRO_PLACE_ERROR,
                flow.BIRTH_PLACE_INVALID,
                reply_markup=flow.cancel_keyboard(),
                state=state,
            )
            return
        except GeocodingError:
            logger.warning("birth_place_lookup_failed")
            await show_screen(
                message,
                Scene.ASTRO_PLACE_ERROR,
                flow.BIRTH_PLACE_UNAVAILABLE,
                reply_markup=flow.cancel_keyboard(),
                state=state,
            )
            return
        if not places:
            await show_screen(
                message,
                Scene.ASTRO_PLACE_ERROR,
                flow.BIRTH_PLACE_EMPTY,
                reply_markup=flow.cancel_keyboard(),
                state=state,
            )
            return
        await state.update_data(places=[_place_payload(place) for place in places])
        await state.set_state(HoroscopeStates.waiting_for_place_choice)
        await show_screen(
            message,
            Scene.ASTRO_PLACE_CHOICE,
            flow.BIRTH_PLACE_PROMPT,
            reply_markup=flow.place_choice_keyboard([place.label for place in places]),
            state=state,
        )

    async def retry_place(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        onboarding: OnboardingService,
        privacy_retention_days: int,
    ) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        if not await ensure_consent(
            callback.message,
            callback.from_user.id,
            state,
            onboarding,
            privacy_retention_days,
            destination=HOROSCOPE_FLOW.namespace,
        ):
            return
        await state.set_state(HoroscopeStates.waiting_for_birth_place)
        await show_screen(
            callback.message,
            Scene.ASTRO_BIRTH_PLACE,
            flow.BIRTH_PLACE_PROMPT,
            reply_markup=flow.cancel_keyboard(),
            state=state,
        )

    async def choose_place(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        onboarding: OnboardingService,
        privacy_retention_days: int,
    ) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        if not await ensure_consent(
            callback.message,
            callback.from_user.id,
            state,
            onboarding,
            privacy_retention_days,
            destination=HOROSCOPE_FLOW.namespace,
        ):
            return
        raw = (callback.data or "").removeprefix(flow.callback("place", "pick", ""))
        stored = (await state.get_data()).get("places")
        place = _selected_place(stored, raw)
        if place is None:
            await state.set_state(HoroscopeStates.waiting_for_birth_place)
            await show_screen(
                callback.message,
                Scene.ASTRO_BIRTH_PLACE,
                flow.BIRTH_PLACE_PROMPT,
                reply_markup=flow.cancel_keyboard(),
                state=state,
            )
            return
        await state.update_data(place=_place_payload(place))
        await state.set_state(HoroscopeStates.waiting_for_birth_time)
        await show_screen(
            callback.message,
            Scene.ASTRO_BIRTH_TIME,
            flow.BIRTH_TIME_PROMPT,
            reply_markup=flow.birth_time_keyboard(),
            state=state,
        )

    async def receive_birth_time(
        self,
        message: Message,
        state: FSMContext,
        onboarding: OnboardingService,
        birth_profile_service: BirthProfileService,
        birth_place_lookup: BirthPlaceLookupService,
        privacy_retention_days: int,
    ) -> None:
        if message.from_user is None:
            return
        if not await ensure_consent(
            message,
            message.from_user.id,
            state,
            onboarding,
            privacy_retention_days,
            destination=HOROSCOPE_FLOW.namespace,
        ):
            return
        parsed = _parse_time(message.text)
        if parsed is None:
            await show_screen(
                message,
                Scene.ASTRO_BIRTH_TIME,
                flow.BIRTH_TIME_INVALID,
                reply_markup=flow.birth_time_keyboard(),
                state=state,
            )
            return
        await self._save_profile(
            message,
            message.from_user.id,
            state,
            onboarding,
            birth_profile_service,
            birth_place_lookup,
            birth_time=parsed,
        )

    async def skip_birth_time(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        onboarding: OnboardingService,
        birth_profile_service: BirthProfileService,
        birth_place_lookup: BirthPlaceLookupService,
        privacy_retention_days: int,
    ) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        if not await ensure_consent(
            callback.message,
            callback.from_user.id,
            state,
            onboarding,
            privacy_retention_days,
            destination=HOROSCOPE_FLOW.namespace,
        ):
            return
        await self._save_profile(
            callback.message,
            callback.from_user.id,
            state,
            onboarding,
            birth_profile_service,
            birth_place_lookup,
            birth_time=None,
        )

    async def choose_offset(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        onboarding: OnboardingService,
        birth_profile_service: BirthProfileService,
        birth_place_lookup: BirthPlaceLookupService,
        privacy_retention_days: int,
    ) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        if not await ensure_consent(
            callback.message,
            callback.from_user.id,
            state,
            onboarding,
            privacy_retention_days,
            destination=HOROSCOPE_FLOW.namespace,
        ):
            return
        raw = (callback.data or "").removeprefix(flow.callback("offset", "pick", ""))
        data = await state.get_data()
        birth_time = _stored_time(data.get("birth_time"))
        try:
            offset = int(raw)
        except ValueError:
            offset = None
        if offset is None or offset not in _stored_offsets(data.get("offsets")):
            await show_screen(
                callback.message,
                Scene.ASTRO_BIRTH_TIME,
                flow.BIRTH_TIME_PROMPT,
                reply_markup=flow.birth_time_keyboard(),
                state=state,
            )
            await state.set_state(HoroscopeStates.waiting_for_birth_time)
            return
        await self._save_profile(
            callback.message,
            callback.from_user.id,
            state,
            onboarding,
            birth_profile_service,
            birth_place_lookup,
            birth_time=birth_time,
            utc_offset_minutes=offset,
        )

    # ---------------------------------------------------------------- profile ---

    async def show_profile(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        onboarding: OnboardingService,
        birth_profile_service: BirthProfileService,
        privacy_retention_days: int,
    ) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        if not await ensure_consent(
            callback.message,
            callback.from_user.id,
            state,
            onboarding,
            privacy_retention_days,
            destination=HOROSCOPE_FLOW.namespace,
        ):
            return
        user = await onboarding.current_user(callback.from_user.id)
        if user is None:
            await state.clear()
            await callback.message.answer(NOT_ONBOARDED)
            return
        try:
            view = await birth_profile_service.load(user.id)
        except BirthProfileConsentRequiredError:
            await self._ask_consent(callback.message, state)
            return
        if view is None:
            await show_screen(
                callback.message,
                Scene.ASTRO_PROFILE,
                flow.PROFILE_MISSING,
                reply_markup=flow.profile_keyboard(),
                state=state,
            )
            return
        await state.clear()
        summary = _profile_summary(
            view.profile.birth_place,
            view.profile.birth_date,
            view.profile.birth_time,
        )
        await show_screen(
            callback.message,
            Scene.ASTRO_PROFILE,
            f"{flow.PROFILE_TITLE}\n{summary}",
            reply_markup=flow.profile_keyboard(),
            state=state,
        )

    async def edit_profile(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        onboarding: OnboardingService,
        privacy_retention_days: int,
    ) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        if not await ensure_consent(
            callback.message,
            callback.from_user.id,
            state,
            onboarding,
            privacy_retention_days,
            destination=HOROSCOPE_FLOW.namespace,
        ):
            return
        await self._ask_birth_date(callback.message, state)

    async def delete_profile(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        onboarding: OnboardingService,
        birth_profile_service: BirthProfileService,
    ) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        user = await onboarding.current_user(callback.from_user.id)
        if user is None:
            await state.clear()
            await callback.message.answer(NOT_ONBOARDED)
            return
        # Revoking consent also purges the stored ciphertext, so one action removes both.
        await birth_profile_service.revoke_consent(user.id)
        await state.clear()
        await show_screen(
            callback.message,
            Scene.ASTRO_PROFILE_DELETED,
            flow.PROFILE_DELETED,
            reply_markup=main_menu_keyboard(),
            state=state,
        )

    # ---------------------------------------------------------- reading intake ---

    async def select_topic(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        onboarding: OnboardingService,
        privacy_retention_days: int,
        oracle_analytics: OracleProductAnalytics | None = None,
    ) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        if not await ensure_consent(
            callback.message,
            callback.from_user.id,
            state,
            onboarding,
            privacy_retention_days,
            destination=HOROSCOPE_FLOW.namespace,
        ):
            return
        topic = (callback.data or "").removeprefix(flow.callback("topic", ""))
        if topic not in flow.HOROSCOPE_TOPIC_LABELS:
            await show_screen(
                callback.message,
                Scene.ASTRO_PROFILE_SAVED,
                "Эта тема недоступна.",
                reply_markup=flow.topics_keyboard(),
                state=state,
            )
            return
        user = await onboarding.current_user(callback.from_user.id)
        if user is not None and oracle_analytics is not None:
            await oracle_analytics.track(
                user.id,
                OracleProductEvent.PERSONA_SELECTED,
                {"persona_code": HOROSCOPE_FLOW.persona_code, "topic_code": topic},
            )
        await state.update_data(topic=topic)
        await state.set_state(HoroscopeStates.waiting_for_question)
        await show_screen(
            callback.message,
            Scene.QUESTION,
            QUESTION_PROMPT,
            reply_markup=HOROSCOPE_FLOW.question_keyboard(),
            state=state,
        )

    async def show_example(self, callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        data = await state.get_data()
        example = flow.HOROSCOPE_TOPIC_EXAMPLES.get(str(data.get("topic")))
        if example is None:
            await show_screen(
                callback.message,
                Scene.QUESTION_ERROR,
                "Эта тема недоступна.",
                reply_markup=flow.topics_keyboard(),
                state=state,
            )
            return
        await show_screen(
            callback.message,
            Scene.QUESTION,
            QUESTION_EXAMPLE.format(example=example),
            reply_markup=HOROSCOPE_FLOW.question_keyboard(),
            state=state,
        )

    async def receive_question(
        self,
        message: Message,
        state: FSMContext,
        onboarding: OnboardingService,
        horoscope_use_case: UseCase,
        horoscope_renderer: HoroscopeRenderer,
        reading_full_price_label: str,
        privacy_retention_days: int,
        oracle_memory: OracleMemoryService | None = None,
    ) -> None:
        if message.from_user is None:
            return
        if not await ensure_consent(
            message,
            message.from_user.id,
            state,
            onboarding,
            privacy_retention_days,
            destination=HOROSCOPE_FLOW.namespace,
        ):
            return
        text = _bounded_text(message, maximum=QUESTION_LIMIT)
        if text is None:
            await show_screen(
                message,
                Scene.QUESTION_ERROR,
                INVALID_TEXT,
                reply_markup=HOROSCOPE_FLOW.question_keyboard(),
                state=state,
            )
            return
        await state.update_data(question=text)
        await self._generate(
            message,
            message.from_user.id,
            state,
            onboarding,
            horoscope_use_case,
            horoscope_renderer,
            context=None,
            price_label=reading_full_price_label,
            oracle_memory=oracle_memory,
        )

    async def receive_context(
        self,
        message: Message,
        state: FSMContext,
        onboarding: OnboardingService,
        horoscope_use_case: UseCase,
        horoscope_renderer: HoroscopeRenderer,
        reading_full_price_label: str,
        privacy_retention_days: int,
        oracle_memory: OracleMemoryService | None = None,
    ) -> None:
        if message.from_user is None:
            return
        if not await ensure_consent(
            message,
            message.from_user.id,
            state,
            onboarding,
            privacy_retention_days,
            destination=HOROSCOPE_FLOW.namespace,
        ):
            return
        context = _bounded_text(message, maximum=CONTEXT_LIMIT)
        if context is None:
            await show_screen(
                message,
                Scene.QUESTION_ERROR,
                INVALID_TEXT,
                reply_markup=HOROSCOPE_FLOW.context_keyboard(),
                state=state,
            )
            return
        await self._generate(
            message,
            message.from_user.id,
            state,
            onboarding,
            horoscope_use_case,
            horoscope_renderer,
            context=context,
            price_label=reading_full_price_label,
            oracle_memory=oracle_memory,
        )

    async def skip_context(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        onboarding: OnboardingService,
        horoscope_use_case: UseCase,
        horoscope_renderer: HoroscopeRenderer,
        reading_full_price_label: str,
        privacy_retention_days: int,
        oracle_memory: OracleMemoryService | None = None,
    ) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        if not await ensure_consent(
            callback.message,
            callback.from_user.id,
            state,
            onboarding,
            privacy_retention_days,
            destination=HOROSCOPE_FLOW.namespace,
        ):
            return
        await self._generate(
            callback.message,
            callback.from_user.id,
            state,
            onboarding,
            horoscope_use_case,
            horoscope_renderer,
            context=None,
            price_label=reading_full_price_label,
            oracle_memory=oracle_memory,
        )

    async def already_generating(self, message: Message, state: FSMContext) -> None:
        await show_screen(
            message,
            Scene.GENERATION_IN_PROGRESS,
            HOROSCOPE_FLOW.texts.already_processing,
            state=state,
        )

    # ---------------------------------------------------------------- history ---

    async def show_history(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        onboarding: OnboardingService,
        reading_history: ReadingHistoryService,
    ) -> None:
        await callback.answer()
        if isinstance(callback.message, Message):
            await self._show_history(
                callback.message, callback.from_user.id, state, onboarding, reading_history, page=0
            )

    async def show_history_page(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        onboarding: OnboardingService,
        reading_history: ReadingHistoryService,
    ) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        prefix = flow.callback("history", "page", "")
        try:
            page = int((callback.data or "").removeprefix(prefix))
        except ValueError:
            page = 0
        await self._show_history(
            callback.message,
            callback.from_user.id,
            state,
            onboarding,
            reading_history,
            page=max(page, 0),
        )

    async def open_from_history(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        onboarding: OnboardingService,
        horoscope_use_case: UseCase,
        horoscope_renderer: HoroscopeRenderer,
        reading_full_price_label: str,
        oracle_memory: OracleMemoryService | None = None,
    ) -> None:
        await callback.answer()
        await self._regenerate(
            callback,
            state,
            onboarding,
            horoscope_use_case,
            horoscope_renderer,
            price_label=reading_full_price_label,
            oracle_memory=oracle_memory,
            prefix=flow.callback("history", "open", ""),
            notice=HOROSCOPE_FLOW.texts.opening,
            notice_scene=Scene.HISTORY_OPEN,
        )

    # ----------------------------------------------------------------- result ---

    async def retry(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        onboarding: OnboardingService,
        horoscope_use_case: UseCase,
        horoscope_renderer: HoroscopeRenderer,
        reading_full_price_label: str,
        oracle_memory: OracleMemoryService | None = None,
    ) -> None:
        await callback.answer()
        await self._regenerate(
            callback,
            state,
            onboarding,
            horoscope_use_case,
            horoscope_renderer,
            price_label=reading_full_price_label,
            oracle_memory=oracle_memory,
            prefix=flow.callback("retry", ""),
            notice=HOROSCOPE_FLOW.texts.processing,
            notice_scene=Scene.GENERATING,
        )

    async def unlock(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        onboarding: OnboardingService,
        horoscope_use_case: UseCase,
        horoscope_monetized: MonetizedReadingService,
        horoscope_renderer: HoroscopeRenderer,
        billing_catalog: BillingCatalog,
        billing_settings: Settings,
        reading_full_price_label: str,
        oracle_memory: OracleMemoryService | None = None,
    ) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        user = await onboarding.current_user(callback.from_user.id)
        if user is None:
            await state.clear()
            await callback.message.answer(NOT_ONBOARDED)
            return
        reading_id = _reading_id(callback.data, flow.callback("unlock", ""))
        if reading_id is None:
            await self._answer_unavailable(callback.message, state)
            return
        await show_screen(callback.message, Scene.UNLOCKING, UNLOCKING, state=state)
        unlocked = await horoscope_monetized.unlock_full(reading_id, user.id)
        if unlocked.status is MonetizedReadingStatus.INSUFFICIENT_CREDITS:
            await show_screen(
                callback.message,
                Scene.INSUFFICIENT_CREDITS,
                texts.PAYWALL.format(price=reading_full_price_label),
                reply_markup=products_keyboard(
                    billing_catalog,
                    billing_settings,
                    resume_callback=flow.callback("unlock", str(reading_id)),
                ),
                state=state,
            )
            return
        if unlocked.status is MonetizedReadingStatus.FULL_COMPLETED:
            outcome = await horoscope_use_case.generate_existing_preview(reading_id, user.id)
            if _renderable(outcome):
                await self._send(
                    callback.message,
                    state,
                    outcome,
                    horoscope_renderer,
                    full=True,
                    user_id=user.id,
                    oracle_memory=oracle_memory,
                )
                return
        await show_screen(
            callback.message,
            Scene.GENERATION_FAILED,
            HOROSCOPE_FLOW.texts.unlock_failed,
            reply_markup=HOROSCOPE_FLOW.result_keyboard(),
            state=state,
        )

    # ---------------------------------------------------------------- internal ---

    async def _start(
        self,
        message: Message,
        telegram_user_id: int,
        state: FSMContext,
        onboarding: OnboardingService,
        birth_profile_service: BirthProfileService,
        identity: TelegramIdentity,
        privacy_retention_days: int,
    ) -> None:
        if not await ensure_consent(
            message,
            telegram_user_id,
            state,
            onboarding,
            privacy_retention_days,
            identity=identity,
            destination=HOROSCOPE_FLOW.namespace,
        ):
            return
        user = await onboarding.current_user(telegram_user_id)
        if user is None:
            await state.clear()
            await message.answer(NOT_ONBOARDED)
            return
        consent = await birth_profile_service.consent_state(user.id)
        if consent is None or consent.status is not BirthProfileConsentStatus.GRANTED:
            await self._ask_consent(message, state)
            return
        try:
            view = await birth_profile_service.load(user.id)
        except BirthProfileConsentRequiredError:
            await self._ask_consent(message, state)
            return
        if view is None:
            await self._ask_birth_date(message, state)
            return
        await state.clear()
        await show_screen(
            message,
            Scene.ASTRO_PROFILE_SAVED,
            HOROSCOPE_FLOW.texts.welcome,
            reply_markup=flow.topics_keyboard(),
            state=state,
        )

    async def _ask_consent(self, message: Message, state: FSMContext) -> None:
        await state.set_state(HoroscopeStates.waiting_for_consent)
        await show_screen(
            message,
            Scene.ASTRO_CONSENT,
            flow.CONSENT,
            reply_markup=flow.consent_keyboard(),
            state=state,
        )

    async def _ask_birth_date(self, message: Message, state: FSMContext) -> None:
        await state.set_state(HoroscopeStates.waiting_for_birth_date)
        await show_screen(
            message,
            Scene.ASTRO_BIRTH_DATE,
            flow.BIRTH_DATE_PROMPT,
            reply_markup=flow.cancel_keyboard(),
            state=state,
        )

    async def _save_profile(
        self,
        message: Message,
        telegram_user_id: int,
        state: FSMContext,
        onboarding: OnboardingService,
        birth_profile_service: BirthProfileService,
        birth_place_lookup: BirthPlaceLookupService,
        *,
        birth_time: time | None,
        utc_offset_minutes: int | None = None,
    ) -> None:
        user = await onboarding.current_user(telegram_user_id)
        data = await state.get_data()
        birth_date = _stored_date(data.get("birth_date"))
        place = _stored_place(data.get("place"))
        if user is None or birth_date is None or place is None:
            await state.clear()
            await show_screen(
                message,
                Scene.ASTRO_PROFILE,
                flow.PROFILE_MISSING,
                reply_markup=HOROSCOPE_FLOW.result_keyboard(),
                state=state,
            )
            return
        try:
            profile = birth_place_lookup.build_profile(
                place, birth_date, birth_time, utc_offset_minutes
            )
        except AmbiguousBirthTimeError as ambiguous:
            await self._ask_which_hour(message, state, birth_time, ambiguous.offsets)
            return
        except UnresolvableBirthPlaceError:
            await show_screen(
                message,
                Scene.ASTRO_PLACE_ERROR,
                flow.BIRTH_MOMENT_INVALID,
                reply_markup=flow.birth_time_keyboard(),
                state=state,
            )
            return
        try:
            await birth_profile_service.save(user.id, profile)
        except BirthProfileConsentRequiredError:
            await self._ask_consent(message, state)
            return
        await state.clear()
        await show_screen(
            message,
            Scene.ASTRO_UNKNOWN_TIME if birth_time is None else Scene.ASTRO_PROFILE_SAVED,
            flow.PROFILE_SAVED,
            reply_markup=flow.topics_keyboard(),
            state=state,
        )

    async def _ask_which_hour(
        self,
        message: Message,
        state: FSMContext,
        birth_time: time | None,
        offsets: tuple[int, ...],
    ) -> None:
        """The clocks went back: one hour of guessing would move the ascendant."""
        clock = birth_time.strftime(TIME_FORMAT) if birth_time is not None else "это время"
        await state.update_data(
            birth_time=None if birth_time is None else birth_time.isoformat(),
            offsets=list(offsets),
        )
        await state.set_state(HoroscopeStates.waiting_for_time_choice)
        await show_screen(
            message,
            Scene.ASTRO_AMBIGUOUS_TIME,
            flow.BIRTH_TIME_AMBIGUOUS.format(clock=clock),
            reply_markup=flow.time_choice_keyboard(offsets, clock),
            state=state,
        )

    async def _show_history(
        self,
        message: Message,
        telegram_user_id: int,
        state: FSMContext,
        onboarding: OnboardingService,
        history: ReadingHistoryService,
        *,
        page: int,
    ) -> None:
        await state.clear()
        user = await onboarding.current_user(telegram_user_id)
        if user is None:
            await message.answer(NOT_ONBOARDED)
            return
        history_page = await history.list_ready(user.id, HOROSCOPE_FLOW.persona_code, page=page)
        labels = [
            (
                item.reading_id,
                f"{_history_label(item.topic)} · {item.created_at:%d.%m.%Y}",
            )
            for item in history_page.items
        ]
        await show_screen(
            message,
            Scene.HISTORY if labels else Scene.HISTORY_EMPTY,
            HOROSCOPE_FLOW.texts.history_title if labels else HOROSCOPE_FLOW.texts.history_empty,
            reply_markup=HOROSCOPE_FLOW.history_keyboard(
                labels, page=history_page.page, has_next=history_page.has_next
            ),
            state=state,
        )

    async def _generate(
        self,
        message: Message,
        telegram_user_id: int,
        state: FSMContext,
        onboarding: OnboardingService,
        use_case: UseCase,
        renderer: HoroscopeRenderer,
        *,
        context: str | None,
        price_label: str,
        oracle_memory: OracleMemoryService | None,
    ) -> None:
        user = await onboarding.current_user(telegram_user_id)
        data = await state.get_data()
        topic = data.get("topic")
        question = data.get("question")
        if user is None or not isinstance(topic, str) or not isinstance(question, str):
            await state.clear()
            await self._answer_unavailable(message, state)
            return
        await state.set_state(HoroscopeStates.generating)
        await show_screen(message, Scene.GENERATING, HOROSCOPE_FLOW.texts.processing, state=state)
        try:
            outcome = await use_case.create_preview(
                user.id,
                HoroscopePreviewRequest(
                    topic=HoroscopeScope(topic),
                    question=question,
                    context=context,
                ),
            )
        except (LookupError, ValueError, PermissionError):
            await state.clear()
            await self._answer_unavailable(message, state)
            return
        await self._deliver(
            message,
            state,
            outcome,
            renderer,
            price_label,
            user_id=user.id,
            oracle_memory=oracle_memory,
        )

    async def _regenerate(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        onboarding: OnboardingService,
        use_case: UseCase,
        renderer: HoroscopeRenderer,
        *,
        price_label: str,
        oracle_memory: OracleMemoryService | None,
        prefix: str,
        notice: str,
        notice_scene: Scene,
    ) -> None:
        if not isinstance(callback.message, Message):
            return
        user = await onboarding.current_user(callback.from_user.id)
        if user is None:
            await state.clear()
            await callback.message.answer(NOT_ONBOARDED)
            return
        reading_id = _reading_id(callback.data, prefix)
        if reading_id is None:
            await self._answer_unavailable(callback.message, state)
            return
        await state.set_state(HoroscopeStates.generating)
        await show_screen(callback.message, notice_scene, notice, state=state)
        outcome = await use_case.generate_existing_preview(reading_id, user.id)
        await self._deliver(
            callback.message,
            state,
            outcome,
            renderer,
            price_label,
            user_id=user.id,
            oracle_memory=oracle_memory,
        )

    async def _deliver(
        self,
        message: Message,
        state: FSMContext,
        outcome: HoroscopePreviewOutcome,
        renderer: HoroscopeRenderer,
        price_label: str,
        *,
        user_id: UUID,
        oracle_memory: OracleMemoryService | None,
    ) -> None:
        await state.clear()
        if _renderable(outcome):
            if outcome.visibility is ReadingPreviewVisibility.FULL:
                await self._send(
                    message,
                    state,
                    outcome,
                    renderer,
                    full=True,
                    user_id=user_id,
                    oracle_memory=oracle_memory,
                )
                return
            if outcome.visibility is ReadingPreviewVisibility.PREVIEW:
                await self._send(
                    message,
                    state,
                    outcome,
                    renderer,
                    full=False,
                    markup=HOROSCOPE_FLOW.result_keyboard(outcome.reading_id, price_label),
                )
                return
            await self._send(
                message,
                state,
                outcome,
                renderer,
                full=False,
                micro=True,
                markup=HOROSCOPE_FLOW.result_keyboard(outcome.reading_id, price_label),
            )
            return

        status = outcome.generation.status
        if status is HoroscopeGenerationStatus.ALREADY_PROCESSING:
            await show_screen(
                message,
                Scene.GENERATION_IN_PROGRESS,
                HOROSCOPE_FLOW.texts.already_processing,
                reply_markup=HOROSCOPE_FLOW.retry_keyboard(outcome.reading_id),
                state=state,
            )
            return
        if status is HoroscopeGenerationStatus.FAILED:
            await show_screen(
                message,
                Scene.GENERATION_FAILED,
                HOROSCOPE_FLOW.texts.failed,
                reply_markup=HOROSCOPE_FLOW.retry_keyboard(outcome.reading_id),
                state=state,
            )
            return
        await self._answer_unavailable(message, state)
        logger.warning(
            "horoscope_delivery_unavailable reading_id=%s status=%s",
            outcome.reading_id,
            status.value,
        )

    async def _send(
        self,
        message: Message,
        state: FSMContext,
        outcome: HoroscopePreviewOutcome,
        renderer: HoroscopeRenderer,
        *,
        full: bool,
        micro: bool = False,
        markup: InlineKeyboardMarkup | None = None,
        user_id: UUID | None = None,
        oracle_memory: OracleMemoryService | None = None,
    ) -> None:
        result = outcome.generation.result
        facts = outcome.generation.facts
        if result is None or facts is None:
            await self._answer_unavailable(message, state)
            return
        if full:
            rendered = renderer.render(result, facts)
        elif micro:
            rendered = renderer.render_micro_preview(result, facts)
        else:
            rendered = renderer.render_preview(result, facts)
        chunks = rendered.chunks()
        offer_memory = False
        if full and user_id is not None and oracle_memory is not None:
            try:
                offer_memory = await oracle_memory.should_offer_consent(user_id)
            except Exception:
                logger.warning("memory_offer_check_failed", exc_info=True)
        final = markup or HOROSCOPE_FLOW.full_result_keyboard(outcome.reading_id)
        for index, chunk in enumerate(chunks):
            reply_markup = final if index == len(chunks) - 1 else None
            if index == 0:
                await send_artifact(
                    message,
                    (
                        Scene.FULL_READING
                        if full
                        else Scene.PREVIEW_ALREADY_USED
                        if micro
                        else Scene.PREVIEW
                    ),
                    chunk,
                    reply_markup=reply_markup,
                    state=state,
                )
            else:
                await message.answer(chunk, reply_markup=reply_markup)
        if offer_memory:
            await show_screen(
                message,
                Scene.MEMORY_DISABLED,
                "Хотите, чтобы Globa помнил важный контекст для следующих разборов? "
                "Память включается только с вашего согласия, а записи можно удалить "
                "в любой момент.",
                reply_markup=memory_disabled_keyboard(),
                state=state,
            )

    async def _answer_unavailable(self, message: Message, state: FSMContext) -> None:
        await show_screen(
            message,
            Scene.GENERATION_FAILED,
            HOROSCOPE_FLOW.texts.unavailable,
            reply_markup=HOROSCOPE_FLOW.result_keyboard(),
            state=state,
        )


def _renderable(outcome: HoroscopePreviewOutcome) -> bool:
    return (
        outcome.generation.status is HoroscopeGenerationStatus.COMPLETED
        and outcome.generation.result is not None
        and outcome.generation.facts is not None
    )


def _history_label(topic: str) -> str:
    """A stored horoscope topic carries a scope and may carry a reference date."""
    scope = topic.split(":", 1)[0]
    return flow.HOROSCOPE_TOPIC_LABELS.get(scope, HOROSCOPE_FLOW.texts.history_fallback)


def _profile_summary(place: str, birth_date: date, birth_time: time | None) -> str:
    when = birth_date.strftime(DATE_FORMAT)
    clock = birth_time.strftime(TIME_FORMAT) if birth_time is not None else "время неизвестно"
    return f"{place}\n{when}, {clock}"


def _place_payload(place: GeocodedPlace) -> dict[str, Any]:
    return {
        "label": place.label,
        "latitude": place.latitude,
        "longitude": place.longitude,
        "timezone": place.timezone,
    }


def _stored_place(payload: object) -> GeocodedPlace | None:
    if not isinstance(payload, dict):
        return None
    try:
        return GeocodedPlace(
            label=str(payload["label"]),
            latitude=float(payload["latitude"]),
            longitude=float(payload["longitude"]),
            timezone=str(payload["timezone"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _selected_place(stored: object, raw_index: str) -> GeocodedPlace | None:
    if not isinstance(stored, list):
        return None
    try:
        index = int(raw_index)
    except ValueError:
        return None
    if not 0 <= index < len(stored):
        return None
    return _stored_place(stored[index])


def _stored_time(value: object) -> time | None:
    if not isinstance(value, str):
        return None
    try:
        return time.fromisoformat(value)
    except ValueError:
        return None


def _stored_offsets(value: object) -> tuple[int, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, int) and not isinstance(item, bool))


def _stored_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_date(value: str | None) -> date | None:
    """Reject a future date here, before the place query reaches the geocoder."""
    if value is None:
        return None
    try:
        parsed = datetime.strptime(value.strip(), DATE_FORMAT).date()  # noqa: DTZ007
    except ValueError:
        return None
    return None if parsed > datetime.now(UTC).date() else parsed


def _parse_time(value: str | None) -> time | None:
    if value is None:
        return None
    try:
        return datetime.strptime(value.strip(), TIME_FORMAT).time()  # noqa: DTZ007
    except ValueError:
        return None


def _reading_id(data: str | None, prefix: str) -> UUID | None:
    try:
        return UUID((data or "").removeprefix(prefix))
    except ValueError:
        return None


def _bounded_text(message: Message, *, maximum: int) -> str | None:
    if message.text is None:
        return None
    value = message.text.strip()
    if not value or len(value) > maximum:
        return None
    return value
