"""Small persistent resume token for horoscope entry points.

The FSM storage is PostgreSQL-backed in production, so a short non-sensitive intent code
survives worker restarts while the user completes global consent or the birth-profile
intake. The code is consumed once the original horoscope screen is restored.
"""

from dataclasses import dataclass

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot import horoscope_flow as flow
from app.bot.scene_media import Scene
from app.bot.screen import show_screen
from app.bot.states import HoroscopeStates

PENDING_HOROSCOPE_INTENT_KEY = "horoscope_pending_intent"
DAY_FORECAST_INTENT = "day_forecast"

PERSONAL_DAILY_PROMPT = (
    "✨ Сегодня для вас\n\n"
    "Общий гороскоп — только фон. Теперь можно посмотреть, где сегодняшний день касается именно "
    "вашей истории. Что важнее: отношения, работа, деньги или общее направление? Можно задать "
    "свой вопрос — не нужно формулировать его «правильно»."
)


@dataclass(frozen=True, slots=True)
class HoroscopeIntent:
    topic: str
    prompt: str


_INTENTS = {
    DAY_FORECAST_INTENT: HoroscopeIntent(
        topic="day_forecast",
        prompt=PERSONAL_DAILY_PROMPT,
    )
}


def pending_horoscope_intent(data: dict[str, object]) -> HoroscopeIntent | None:
    """Resolve only allow-listed intent codes stored in FSM data."""

    code = data.get(PENDING_HOROSCOPE_INTENT_KEY)
    if not isinstance(code, str):
        return None
    return _INTENTS.get(code)


async def remember_horoscope_intent(state: FSMContext, code: str) -> None:
    """Persist a non-sensitive entry intent without disturbing the current FSM state."""

    if code not in _INTENTS:
        raise ValueError("unsupported horoscope intent")
    await state.update_data({PENDING_HOROSCOPE_INTENT_KEY: code})


async def resume_horoscope_intent(message: Message, state: FSMContext) -> bool:
    """Consume a pending intent and restore the exact horoscope question screen."""

    intent = pending_horoscope_intent(await state.get_data())
    if intent is None:
        return False
    await state.clear()
    await state.update_data(topic=intent.topic)
    await state.set_state(HoroscopeStates.waiting_for_question)
    await show_screen(
        message,
        Scene.QUESTION,
        intent.prompt,
        reply_markup=flow.HOROSCOPE_FLOW.question_keyboard(),
        state=state,
    )
    return True
