"""Composed registry for independent versioned oracle prompt packs."""

from app.prompts.mystical_psychologist import MYSTICAL_PSYCHOLOGIST_V2
from app.prompts.reading import ReadingPromptSet, load_reading_prompts
from app.prompts.tarot_v4 import TAROT_READER_V4

_PERSONA_PACKS: dict[str, ReadingPromptSet] = {
    "tarot-reader-v4": TAROT_READER_V4,
    "mystical-psychologist-v2": MYSTICAL_PSYCHOLOGIST_V2,
}


def load_oracle_reading_prompts(version: str) -> ReadingPromptSet:
    """Resolve persona-specific packs without mutating previously frozen prompt modules."""

    pack = _PERSONA_PACKS.get(version)
    if pack is not None:
        return pack
    return load_reading_prompts(version)
