"""Small, non-secret acquisition attribution primitives for Telegram first touch."""

import re
from uuid import UUID

PARTIZAN_START_PREFIX = "ptz_"
_REFERRAL_TOKEN = re.compile(r"^[0-9a-f]{16}$")
_BOT_USERNAME = re.compile(r"^[A-Za-z0-9_]+$")


def referral_token_from_experiment(experiment_id: UUID) -> str:
    """Match Partizan's public referral token without carrying a full UUID into Telegram."""

    return experiment_id.hex[:16]


def normalize_bot_username(value: str) -> str:
    """Normalize a configured Telegram bot username for a safe t.me URL."""

    username = value.strip().removeprefix("@")
    if not username or not _BOT_USERNAME.fullmatch(username):
        raise ValueError("telegram bot username must contain only ASCII letters, digits, or underscore")
    return username


def build_telegram_deep_link(bot_username: str, referral_token: str | None = None) -> str:
    username = normalize_bot_username(bot_username)
    if referral_token is None:
        return f"https://t.me/{username}"
    if not _REFERRAL_TOKEN.fullmatch(referral_token):
        raise ValueError("invalid Partizan referral token")
    return f"https://t.me/{username}?start={PARTIZAN_START_PREFIX}{referral_token}"


def parse_partizan_start_payload(message_text: str | None) -> str | None:
    """Return only the bounded Partizan payload from an exact Telegram /start command."""

    if not message_text:
        return None
    parts = message_text.strip().split(maxsplit=1)
    if len(parts) != 2:
        return None
    command, payload = parts
    command = command.split("@", 1)[0]
    if command != "/start" or not payload.startswith(PARTIZAN_START_PREFIX):
        return None
    token = payload.removeprefix(PARTIZAN_START_PREFIX).lower()
    return token if _REFERRAL_TOKEN.fullmatch(token) else None
