"""Telegram delivery for the hosted-checkout completion notice.

The button routes to `credits:refresh`, which is the balance screen. That screen already
recovers the concrete reading the paywall was opened for from durable FSM state and offers
"После оплаты открыть разбор", so the buyer reaches their reading without this worker
needing to know — or store — which reading was being unlocked.
"""

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot import texts
from app.services.purchase_notification_service import NotifierError


def purchase_received_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=texts.PURCHASE_RECEIVED_BUTTON,
                    callback_data="credits:refresh",
                )
            ]
        ]
    )


class TelegramBuyerNotifier:
    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def notify_purchase(self, telegram_user_id: int, readings: int) -> None:
        try:
            await self._bot.send_message(
                telegram_user_id,
                texts.PURCHASE_RECEIVED.format(readings=readings),
                reply_markup=purchase_received_keyboard(),
            )
        except TelegramAPIError as exc:
            raise NotifierError(str(exc)) from exc
