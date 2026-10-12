from app.domain.memory_extraction import CURRENT_MEMORY_EXTRACTION_VERSION
from app.prompts.reading_memory_extraction import (
    READING_MEMORY_EXTRACTION_PROMPT_VERSION,
    READING_MEMORY_EXTRACTION_SYSTEM,
)


def test_memory_extraction_uses_new_versioned_contract() -> None:
    assert CURRENT_MEMORY_EXTRACTION_VERSION == "oracle-memory-extractor-v2"
    assert READING_MEMORY_EXTRACTION_PROMPT_VERSION == "reading-memory-extraction-v2"
    assert "claim_basis=user_stated" in READING_MEMORY_EXTRACTION_SYSTEM
    assert "prefer fewer high-value candidates" in READING_MEMORY_EXTRACTION_SYSTEM.casefold()
