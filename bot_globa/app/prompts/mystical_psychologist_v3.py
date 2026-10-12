"""Editorial-quality upgrade of the Mystical Psychologist prompt pack."""

from app.prompts.editorial_quality import NUMA_EDITORIAL_QUALITY
from app.prompts.mystical_psychologist import MYSTICAL_PSYCHOLOGIST_V2
from app.prompts.reading import ReadingPromptSet

MYSTICAL_PSYCHOLOGIST_V3 = ReadingPromptSet(
    system=MYSTICAL_PSYCHOLOGIST_V2.system + "\n\n" + NUMA_EDITORIAL_QUALITY,
    request_instruction=(
        MYSTICAL_PSYCHOLOGIST_V2.request_instruction
        + "\n\nBefore returning JSON, silently remove generic therapeutic filler and make sure each "
        "pattern names a genuinely different mechanism rather than a synonym of the opening."
    ),
    accepts_memory_context=True,
)
