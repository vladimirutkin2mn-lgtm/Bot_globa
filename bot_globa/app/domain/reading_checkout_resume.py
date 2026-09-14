"""Durable, server-owned resume targets for hosted reading checkouts."""

from base64 import urlsafe_b64decode, urlsafe_b64encode
from binascii import Error as Base64Error
from dataclasses import dataclass
from uuid import UUID

_PERSONA_BY_ROUTE = {
    "tarot": "tarot_reader",
    "love": "love_oracle",
    "psy": "mystical_psychologist",
    "astro": "astrologer",
}
_ROUTE_BY_PERSONA = {persona: route for route, persona in _PERSONA_BY_ROUTE.items()}


@dataclass(frozen=True, slots=True)
class ReadingCheckoutTarget:
    reading_id: UUID
    persona_code: str
    story_id: UUID | None = None

    @property
    def callback_data(self) -> str:
        route = _ROUTE_BY_PERSONA.get(self.persona_code)
        if route is None:
            raise ValueError("unsupported reading persona")
        if self.story_id is None:
            return f"{route}:unlock:{self.reading_id}"
        callback = f"{route}:unlock:{_compact_uuid(self.reading_id)}:{_compact_uuid(self.story_id)}"
        if len(callback.encode("utf-8")) > 64:
            raise ValueError("reading resume callback exceeds Telegram callback-data limit")
        return callback

    def snapshot(self) -> dict[str, str]:
        snapshot = {
            "kind": "reading",
            "reading_id": str(self.reading_id),
            "persona_code": self.persona_code,
        }
        if self.story_id is not None:
            snapshot["story_id"] = str(self.story_id)
        return snapshot


def parse_reading_resume_callback(value: str | None) -> ReadingCheckoutTarget | None:
    """Convert a known unlock callback to structured data; reject everything else."""

    if not value:
        return None
    route, separator, payload = value.partition(":unlock:")
    persona_code = _PERSONA_BY_ROUTE.get(route)
    if not separator or persona_code is None:
        return None

    parts = payload.split(":")
    if len(parts) == 1:
        reading_id = _full_uuid(parts[0])
        if reading_id is None:
            return None
        return ReadingCheckoutTarget(reading_id=reading_id, persona_code=persona_code)
    if len(parts) != 2:
        return None

    reading_id = _expand_uuid(parts[0])
    story_id = _expand_uuid(parts[1])
    if reading_id is None or story_id is None:
        return None
    return ReadingCheckoutTarget(
        reading_id=reading_id,
        persona_code=persona_code,
        story_id=story_id,
    )


def reading_target_from_snapshot(snapshot: dict[str, object]) -> ReadingCheckoutTarget | None:
    """Decode only the structured target shape written by the checkout service."""

    raw = snapshot.get("resume_target")
    if not isinstance(raw, dict) or raw.get("kind") != "reading":
        return None
    raw_reading_id = raw.get("reading_id")
    persona_code = raw.get("persona_code")
    raw_story_id = raw.get("story_id")
    if not isinstance(raw_reading_id, str) or not isinstance(persona_code, str):
        return None
    if persona_code not in _ROUTE_BY_PERSONA:
        return None
    reading_id = _full_uuid(raw_reading_id)
    if reading_id is None:
        return None
    if raw_story_id is None:
        return ReadingCheckoutTarget(reading_id=reading_id, persona_code=persona_code)
    if not isinstance(raw_story_id, str):
        return None
    story_id = _full_uuid(raw_story_id)
    if story_id is None:
        return None
    return ReadingCheckoutTarget(
        reading_id=reading_id,
        persona_code=persona_code,
        story_id=story_id,
    )


def _full_uuid(value: str) -> UUID | None:
    try:
        parsed = UUID(value)
    except ValueError:
        return None
    return parsed if str(parsed) == value.lower() else None


def _compact_uuid(value: UUID) -> str:
    return urlsafe_b64encode(value.bytes).decode("ascii").rstrip("=")


def _expand_uuid(value: str) -> UUID | None:
    if len(value) != 22:
        return None
    try:
        raw = urlsafe_b64decode(f"{value}==".encode("ascii"))
    except (Base64Error, UnicodeEncodeError, ValueError):
        return None
    if len(raw) != 16:
        return None
    parsed = UUID(bytes=raw)
    return parsed if _compact_uuid(parsed) == value else None
