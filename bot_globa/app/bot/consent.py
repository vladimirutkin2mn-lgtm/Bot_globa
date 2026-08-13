"""The just-in-time gate for every screen that stores, bills or remembers personal data.

CJM v2 moved consent out of a blocking onboarding step, so the main menu is reachable
before the terms are accepted. That makes the gate the responsibility of each screen that
acts on personal data: a reading, a purchase, a receipt contact, or memory. A screen that
only shows non-personal content — the common daily digest, the privacy text itself — stays
open, otherwise the consent screen would have nothing to explain.
"""

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot import texts
from app.bot.keyboards import consent_keyboard
from app.bot.scene_media import Scene
from app.bot.screen import show_screen
from app.bot.states import OnboardingStates
from app.services.onboarding import OnboardingService, TelegramIdentity


async def request_consent(
    message: Message,
    state: FSMContext,
    privacy_retention_days: int,
    *,
    destination: str | None = None,
) -> None:
    """Show the terms and remember which screen the user was trying to reach."""

    await state.set_state(OnboardingStates.waiting_for_consent)
    await show_screen(
        message,
        Scene.ONBOARDING_CONSENT,
        texts.CONSENT.format(days=privacy_retention_days),
        reply_markup=consent_keyboard(destination),
        state=state,
    )


async def ensure_consent(
    message: Message,
    telegram_user_id: int,
    state: FSMContext,
    onboarding: OnboardingService,
    privacy_retention_days: int,
    *,
    identity: TelegramIdentity | None = None,
    destination: str | None = None,
) -> bool:
    """Report whether this user may proceed, showing the terms when they may not."""

    if identity is not None and await onboarding.current_user(telegram_user_id) is None:
        await onboarding.start(identity)
    if await onboarding.analysis_allowed(telegram_user_id):
        return True
    await request_consent(message, state, privacy_retention_days, destination=destination)
    return False
