"""Send the image a screen shows, with its Telegram copy.

Most images belong to a client-journey scene, but not all: a tarot reveal shows the
card that was drawn. Both go through the same `file_id` cache and the same graceful
degradation, so `Art` is the unit here rather than `Scene`.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.types import InlineKeyboardMarkup, InputMediaPhoto, Message
from aiogram.types.input_file import FSInputFile

logger = logging.getLogger(__name__)

TELEGRAM_CAPTION_LIMIT = 1024
SCENE_ASSET_DIR = Path(__file__).parent / "assets" / "scenes"


class Scene(StrEnum):
    """Stable IDs shared by the Miro CJM and the Telegram implementation."""

    ONBOARDING_START = "O-01"
    ONBOARDING_CONSENT = "O-03"
    MAIN_MENU = "O-04"
    TAROT_ENTRY = "T-01"
    LOVE_ENTRY = "L-01"
    PSYCHOLOGIST_ENTRY = "P-01"
    ASTRO_CONSENT = "A-01"
    ASTRO_CONSENT_DECLINED = "A-02"
    ASTRO_BIRTH_DATE = "A-03"
    ASTRO_BIRTH_DATE_ERROR = "A-04"
    ASTRO_BIRTH_PLACE = "A-05"
    ASTRO_PLACE_CHOICE = "A-06"
    ASTRO_PLACE_ERROR = "A-07"
    ASTRO_BIRTH_TIME = "A-08"
    ASTRO_UNKNOWN_TIME = "A-09"
    ASTRO_AMBIGUOUS_TIME = "A-10"
    ASTRO_PROFILE_SAVED = "A-11"
    ASTRO_PROFILE = "A-12"
    ASTRO_PROFILE_DELETED = "A-13"
    QUESTION = "G-01"
    QUESTION_ERROR = "G-02"
    CONTEXT = "G-03"
    GENERATING = "G-04"
    PREVIEW = "G-05"
    PREVIEW_ALREADY_USED = "G-06"
    UNLOCKING = "G-07"
    INSUFFICIENT_CREDITS = "G-08"
    FULL_READING = "G-09"
    GENERATION_FAILED = "G-10"
    GENERATION_IN_PROGRESS = "G-11"
    HISTORY = "H-01"
    HISTORY_EMPTY = "H-02"
    HISTORY_OPEN = "H-03"
    FOLLOW_UP_QUESTION = "F-01"
    FOLLOW_UP_GENERATING = "F-02"
    FOLLOW_UP_RESULT = "F-03"
    FOLLOW_UP_ALREADY_USED = "F-04"
    FOLLOW_UP_FAILED = "F-05"
    MEMORY_DISABLED = "M-01"
    MEMORY_ENABLED = "M-02"
    MEMORY_HOME = "M-03"
    MEMORY_LIST = "M-04"
    MEMORY_ITEM = "M-05"
    MEMORY_EDIT = "M-06"
    MEMORY_EDITED = "M-07"
    MEMORY_DELETE_ONE = "M-08"
    MEMORY_DELETE_ALL = "M-09"
    MEMORY_DISABLE = "M-10"
    BALANCE = "B-01"
    PAYMENT_MARKET = "B-02"
    RECEIPT_CONTACT = "B-03"
    CHECKOUT = "B-04"
    CHECKOUT_UNAVAILABLE = "B-05"
    SUBSCRIPTION_CHOICE = "B-06"
    SUBSCRIPTION_CHECKOUT = "B-07"
    SUBSCRIPTION_ACTIVE = "B-08"
    SUBSCRIPTION_CANCEL = "B-09"
    SUBSCRIPTION_RESUME = "B-10"
    SUBSCRIPTION_PAST_DUE = "B-11"
    REFUND_AVAILABLE = "R-01"
    REFUND_UNAVAILABLE = "R-02"
    REFUND_ACCEPTED = "R-03"
    REFUND_HISTORY = "R-04"
    PRIVACY = "D-01"
    DELETE_ACCOUNT = "D-02"
    DELETE_CANCELLED = "D-03"
    ACCOUNT_DELETED = "D-04"
    # Safety scenes exist in the CJM, but a safety hand-off is deliberately sent as plain
    # text: it must reach the user even when Telegram refuses media, and an illustration
    # would dress up a screen whose whole job is to stop the mystical flow.
    CRISIS = "S-01"
    VIOLENCE = "S-02"
    HIGH_STAKES = "S-03"
    # Common daily digest and its delivery settings.
    DAILY_ZODIAC = "E-01"
    DAILY_HOROSCOPE = "E-02"
    DAILY_PERSONAL_CTA = "E-03"
    DAILY_SETTINGS = "E-04"

    @property
    def asset_path(self) -> Path:
        return SCENE_ASSET_DIR / f"{self.value}.jpg"

    @property
    def art(self) -> "Art":
        return Art(key=self.value, path=self.asset_path)


@dataclass(frozen=True, slots=True)
class Art:
    """One image the bot can show, and the key its Telegram `file_id` is cached under.

    The key is what makes a second delivery cheap, so it has to identify the picture
    rather than the screen: two screens showing the same card share one upload.
    """

    key: str
    path: Path


# Keyed by `Art.key` rather than by scene: cards are cached the same way pictures are.
_telegram_file_ids: dict[str, str] = {}

# CJM v2 uses full-width art as punctuation, not chrome. Utility, payment, privacy,
# settings, errors and safety hand-offs stay fast plain-text messages even though their
# legacy scene assets remain available for design reference.
MEDIA_SCENES = frozenset(
    {
        Scene.ONBOARDING_START,
        Scene.TAROT_ENTRY,
        Scene.LOVE_ENTRY,
        Scene.PSYCHOLOGIST_ENTRY,
        Scene.ASTRO_CONSENT,
        Scene.ASTRO_PROFILE_SAVED,
        Scene.GENERATING,
        Scene.GENERATION_IN_PROGRESS,
        Scene.PREVIEW,
        Scene.PREVIEW_ALREADY_USED,
        Scene.FULL_READING,
        Scene.FOLLOW_UP_RESULT,
        Scene.DAILY_ZODIAC,
        Scene.DAILY_HOROSCOPE,
    }
)


async def answer_scene(
    message: Message,
    scene: Scene,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Send one visual Telegram screen and preserve readable long-copy fallback.

    The copy is what the user needs; the illustration is decoration. Telegram can refuse a
    photo for reasons the caller cannot control — a stale `file_id`, a media restriction in
    the chat, a transport failure — so a media error degrades to the plain text instead of
    losing the screen entirely.
    """

    if scene not in MEDIA_SCENES:
        await message.answer(text, reply_markup=reply_markup)
        return

    caption_fits = len(text) <= TELEGRAM_CAPTION_LIMIT
    if not await _send_photo(
        message,
        scene,
        caption=text if caption_fits else None,
        # A caption cannot hold long copy, so the keyboard belongs to the text that follows.
        reply_markup=reply_markup if caption_fits else None,
    ):
        await message.answer(text, reply_markup=reply_markup)
        return
    if not caption_fits:
        await message.answer(text, reply_markup=reply_markup)


async def send_scene_photo(
    bot: Bot,
    chat_id: int,
    scene: Scene,
    caption: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Send a scene outside a handler, reusing the same cached `file_id` the bot uses.

    A worker has no incoming `Message` to answer, and re-uploading the asset for every
    recipient would send the same picture over the wire once per delivery.
    """

    if await _photo_to_chat(bot, chat_id, scene.art, caption, reply_markup) is None:
        await bot.send_message(chat_id=chat_id, text=caption, reply_markup=reply_markup)


def scene_art(scene: Scene) -> Art | None:
    """The illustration a scene carries, or None for the screens CJM v2 keeps plain."""

    return scene.art if scene in MEDIA_SCENES else None


async def send_art(
    bot: Bot,
    chat_id: int,
    art: Art | None,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Message:
    """Deliver one screen as exactly one message, and report which message that became.

    The live screen has to stay editable, so it may never be split across a photo and a
    follow-up text the way a long artifact is: copy that outgrows a caption is delivered
    as text instead of losing the ability to be edited in place.
    """

    if art is not None and len(text) <= TELEGRAM_CAPTION_LIMIT:
        sent = await _photo_to_chat(bot, chat_id, art, text, reply_markup)
        if sent is not None:
            return sent
    return await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)


async def edit_art(
    bot: Bot,
    chat_id: int,
    message_id: int,
    art: Art,
    caption: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> bool:
    """Swap the illustration on an existing photo screen, reporting whether it worked.

    Telegram refuses to replace media on a message it no longer considers editable, and
    the caller has to be able to fall back to a fresh screen rather than leave the user
    looking at the previous step.
    """

    async def swap(photo: str | FSInputFile) -> Message | bool:
        return await bot.edit_message_media(
            chat_id=chat_id,
            message_id=message_id,
            media=InputMediaPhoto(media=photo, caption=caption),
            reply_markup=reply_markup,
        )

    return await _cached_photo(art, swap) is not None


async def _photo_to_chat(
    bot: Bot,
    chat_id: int,
    art: Art,
    caption: str | None,
    reply_markup: InlineKeyboardMarkup | None,
) -> Message | None:
    async def send(photo: str | FSInputFile) -> Message:
        return await bot.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption=caption,
            reply_markup=reply_markup,
        )

    return await _cached_photo(art, send)


async def _send_photo(
    message: Message,
    scene: Scene,
    *,
    caption: str | None,
    reply_markup: InlineKeyboardMarkup | None,
) -> bool:
    """Send the scene illustration, reporting whether the copy still needs a text message."""

    async def send(photo: str | FSInputFile) -> Message:
        if caption is None:
            return await message.answer_photo(photo=photo)
        return await message.answer_photo(photo=photo, caption=caption, reply_markup=reply_markup)

    return await _cached_photo(scene.art, send) is not None


async def _cached_photo[T](
    art: Art,
    send: Callable[[str | FSInputFile], Awaitable[T]],
) -> T | None:
    """Run one photo request against the cached `file_id`, falling back to the asset once.

    A cached `file_id` that Telegram refuses is dropped and the upload retried — otherwise
    a single invalidation would break that scene until the process restarts. A refusal the
    caller cannot control is reported rather than raised: every screen has a text form.
    """

    cached = _telegram_file_ids.get(art.key)
    if cached is not None:
        try:
            sent = await send(cached)
        except TelegramForbiddenError:
            raise
        except TelegramAPIError:
            logger.warning("art_file_id_rejected key=%s", art.key)
            _telegram_file_ids.pop(art.key, None)
        else:
            _remember_file_id(art.key, sent)
            return sent

    try:
        sent = await send(FSInputFile(art.path, filename=art.path.name))
    except TelegramForbiddenError:
        raise
    except TelegramAPIError:
        logger.warning("art_unavailable key=%s", art.key)
        return None
    _remember_file_id(art.key, sent)
    return sent


def _remember_file_id(key: str, message: object) -> None:
    if isinstance(message, Message) and message.photo:
        _telegram_file_ids[key] = message.photo[-1].file_id
