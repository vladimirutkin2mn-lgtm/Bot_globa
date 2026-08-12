"""Send the image assigned to a client-journey scene with its Telegram copy."""

from enum import StrEnum
from pathlib import Path

from aiogram.types import InlineKeyboardMarkup, Message
from aiogram.types.input_file import FSInputFile

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
    CRISIS = "S-01"
    VIOLENCE = "S-02"
    HIGH_STAKES = "S-03"
    DAILY_ZODIAC = "E-01"
    DAILY_HOROSCOPE = "E-02"
    DAILY_PERSONAL_CTA = "E-03"
    DAILY_SETTINGS = "E-04"

    @property
    def asset_path(self) -> Path:
        return SCENE_ASSET_DIR / f"{self.value}.jpg"


_telegram_file_ids: dict[Scene, str] = {}


async def answer_scene(
    message: Message,
    scene: Scene,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Message:
    """Send one visual Telegram screen and preserve readable long-copy fallback."""

    photo: str | FSInputFile = _telegram_file_ids.get(scene) or FSInputFile(
        scene.asset_path,
        filename=f"{scene.value}.jpg",
    )
    if len(text) <= TELEGRAM_CAPTION_LIMIT:
        sent = await message.answer_photo(photo=photo, caption=text, reply_markup=reply_markup)
    else:
        photo_message = await message.answer_photo(photo=photo)
        _remember_file_id(scene, photo_message)
        return await message.answer(text, reply_markup=reply_markup)
    _remember_file_id(scene, sent)
    return sent


def _remember_file_id(scene: Scene, message: object) -> None:
    if isinstance(message, Message) and message.photo:
        _telegram_file_ids[scene] = message.photo[-1].file_id
