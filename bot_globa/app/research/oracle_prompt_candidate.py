"""Single editable prompt surface for Numa LLM autoresearch.

Autonomous experiments may edit this file only. The baseline deliberately proxies the
current production prompt packs exactly; promotion back into production remains a human
decision.
"""

from app.prompts.horoscope import HoroscopePromptSet, load_horoscope_prompts
from app.prompts.oracle import load_oracle_reading_prompts
from app.prompts.reading import ReadingPromptSet

RESEARCH_CANDIDATE_VERSION = "oracle-prompts-v1-baseline"


def load_candidate_reading_prompts(version: str) -> ReadingPromptSet:
    """Return the editable research candidate for non-astrology personas."""

    return load_oracle_reading_prompts(version)


def load_candidate_horoscope_prompts(version: str) -> HoroscopePromptSet:
    """Return the editable research candidate for the astrologer."""

    return load_horoscope_prompts(version)
