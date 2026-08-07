"""Composed registry for independent versioned oracle prompt packs."""

from app.prompts.mystical_psychologist import MYSTICAL_PSYCHOLOGIST_V1
from app.prompts.reading import (
    ReadingPromptNotFoundError,
    ReadingPromptSet,
    load_reading_prompts,
)


def load_oracle_reading_prompts(version: str) -> ReadingPromptSet:
    """Resolve persona-specific packs without mutating previously frozen prompt modules."""

    if version == "mystical-psychologist-v1":
        return MYSTICAL_PSYCHOLOGIST_V1
    try:
        return load_reading_prompts(version)
    except ReadingPromptNotFoundError:
        raise
