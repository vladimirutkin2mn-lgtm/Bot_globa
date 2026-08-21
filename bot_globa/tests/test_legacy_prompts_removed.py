import pytest

from app.prompts.horoscope import (
    HoroscopePromptNotFoundError,
    load_horoscope_prompts,
)
from app.prompts.oracle import load_oracle_reading_prompts
from app.prompts.reading import ReadingPromptNotFoundError


@pytest.mark.parametrize(
    "version",
    [
        "tarot-reader-v4",
        "love-oracle-v2",
        "mystical-psychologist-v2",
    ],
)
def test_active_oracle_prompt_versions_remain_available(version: str) -> None:
    assert load_oracle_reading_prompts(version) is not None


@pytest.mark.parametrize(
    "version",
    [
        "tarot-reader-v1",
        "tarot-reader-v2",
        "tarot-reader-v3",
        "love-oracle-v1",
        "mystical-psychologist-v1",
    ],
)
def test_legacy_oracle_prompt_versions_are_not_deployed(version: str) -> None:
    with pytest.raises(ReadingPromptNotFoundError):
        load_oracle_reading_prompts(version)


def test_active_astrologer_prompt_version_remains_available() -> None:
    assert load_horoscope_prompts("astrologer-v2") is not None


def test_legacy_astrologer_prompt_version_is_not_deployed() -> None:
    with pytest.raises(HoroscopePromptNotFoundError):
        load_horoscope_prompts("astrologer-v1")
