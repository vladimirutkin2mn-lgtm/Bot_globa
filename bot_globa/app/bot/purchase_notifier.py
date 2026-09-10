"""Telegram delivery for hosted-checkout completion notices."""

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot import texts
from app.domain.reading_checkout_resume import parse_reading_resume_callback
from app.services.purchase_notification_service import NotifierError


def purchase_received_keyboard(resume_callback: str | None = None) -> InlineKeyboardMarkup:
    target = parse_reading_resume_callback(resume_callback)
    if target is not None:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Открыть разбор",
                        callback_data=target.callback_data,
                    )
                ]
            ]
        )
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

    async def notify_purchase(
        self,
        telegram_user_id: int,
        readings: int,
        resume_callback: str | None = None,
    ) -> None:
        try:
            await self._bot.send_message(
                telegram_user_id,
                texts.PURCHASE_RECEIVED.format(readings=readings),
                reply_markup=purchase_received_keyboard(resume_callback),
            )
        except TelegramAPIError as exc:
            raise NotifierError(str(exc)) from exc
