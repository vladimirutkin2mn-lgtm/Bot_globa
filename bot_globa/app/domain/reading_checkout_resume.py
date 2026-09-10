"""Durable, server-owned resume targets for hosted reading checkouts."""

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

    @property
    def callback_data(self) -> str:
        route = _ROUTE_BY_PERSONA.get(self.persona_code)
        if route is None:
            raise ValueError("unsupported reading persona")
        return f"{route}:unlock:{self.reading_id}"

    def snapshot(self) -> dict[str, str]:
        return {
            "kind": "reading",
            "reading_id": str(self.reading_id),
            "persona_code": self.persona_code,
        }


def parse_reading_resume_callback(value: str | None) -> ReadingCheckoutTarget | None:
    """Convert a known unlock callback to structured data; reject everything else."""

    if not value:
        return None
    route, separator, raw_reading_id = value.partition(":unlock:")
    persona_code = _PERSONA_BY_ROUTE.get(route)
    if not separator or persona_code is None:
        return None
    try:
        reading_id = UUID(raw_reading_id)
    except ValueError:
        return None
    if str(reading_id) != raw_reading_id.lower():
        return None
    return ReadingCheckoutTarget(reading_id=reading_id, persona_code=persona_code)


def reading_target_from_snapshot(snapshot: dict[str, object]) -> ReadingCheckoutTarget | None:
    """Decode only the structured target shape written by the checkout service."""

    raw = snapshot.get("resume_target")
    if not isinstance(raw, dict) or raw.get("kind") != "reading":
        return None
    raw_reading_id = raw.get("reading_id")
    persona_code = raw.get("persona_code")
    if not isinstance(raw_reading_id, str) or not isinstance(persona_code, str):
        return None
    if persona_code not in _ROUTE_BY_PERSONA:
        return None
    try:
        reading_id = UUID(raw_reading_id)
    except ValueError:
        return None
    return ReadingCheckoutTarget(reading_id=reading_id, persona_code=persona_code)
