"""Send the image assigned to a client-journey scene with its Telegram copy."""

import logging
from enum import StrEnum
from pathlib import Path

from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup, Message
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
    # Common daily digest and its opt-in settings.
    DAILY_ZODIAC = "E-01"
    DAILY_HOROSCOPE = "E-02"
    DAILY_PERSONAL_CTA = "E-03"
    DAILY_SETTINGS = "E-04"

    @property
    def asset_path(self) -> Path:
        return SCENE_ASSET_DIR / f"{self.value}.jpg"


_telegram_file_ids: dict[Scene, str] = {}

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


async def _send_photo(
    message: Message,
    scene: Scene,
    *,
    caption: str | None,
    reply_markup: InlineKeyboardMarkup | None,
) -> bool:
    """Send the scene illustration, reporting whether the copy still needs a text message.

    A cached `file_id` that Telegram refuses is dropped and the upload retried once —
    otherwise a single invalidation would break that scene until the process restarts.
    """

    cached = _telegram_file_ids.get(scene)
    if cached is not None:
        try:
            _remember_file_id(scene, await _photo(message, cached, caption, reply_markup))
        except TelegramAPIError:
            logger.warning("scene_file_id_rejected scene=%s", scene.value)
            _telegram_file_ids.pop(scene, None)
        else:
            return True
    asset = FSInputFile(scene.asset_path, filename=f"{scene.value}.jpg")
    try:
        _remember_file_id(scene, await _photo(message, asset, caption, reply_markup))
    except TelegramAPIError:
        logger.warning("scene_photo_unavailable scene=%s", scene.value)
        return False
    return True


async def _photo(
    message: Message,
    photo: str | FSInputFile,
    caption: str | None,
    reply_markup: InlineKeyboardMarkup | None,
) -> Message:
    if caption is None:
        return await message.answer_photo(photo=photo)
    return await message.answer_photo(photo=photo, caption=caption, reply_markup=reply_markup)


def _remember_file_id(scene: Scene, message: object) -> None:
    if isinstance(message, Message) and message.photo:
        _telegram_file_ids[scene] = message.photo[-1].file_id
