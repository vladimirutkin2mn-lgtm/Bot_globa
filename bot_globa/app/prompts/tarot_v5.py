"""Editorial-quality upgrade of the grounded Tarot Reader prompt pack."""

from app.prompts.editorial_quality import NUMA_EDITORIAL_QUALITY
from app.prompts.reading import ReadingPromptSet
from app.prompts.tarot_v4 import TAROT_READER_V4

TAROT_READER_V5 = ReadingPromptSet(
    system=TAROT_READER_V4.system + "\n\n" + NUMA_EDITORIAL_QUALITY,
    request_instruction=(
        TAROT_READER_V4.request_instruction
        + "\n\nBefore returning JSON, silently check that title, opening, patterns, practical_step and "
        "share_card each add a distinct idea rather than paraphrasing one another."
    ),
    accepts_memory_context=True,
)
