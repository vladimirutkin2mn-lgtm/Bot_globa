"""Allow-listed package-resource loader for the reading follow-up prompt pack.

Self-contained on purpose: the follow-up is the only prompt pack still loaded from files
rather than declared in Python, and it must not depend on anything named after the
retired analysis stack.
"""

from dataclasses import dataclass
from importlib.resources import files

KNOWN_READING_FOLLOWUP_PROMPT_VERSIONS = frozenset({"reading_followup_v1"})


class ReadingFollowUpPromptNotFoundError(ValueError):
    pass


@dataclass(frozen=True)
class ReadingFollowUpPromptSet:
    version: str
    system: str
    request: str
    repair: str


def load_reading_followup_prompts(version: str) -> ReadingFollowUpPromptSet:
    if version not in KNOWN_READING_FOLLOWUP_PROMPT_VERSIONS or "/" in version or ".." in version:
        raise ReadingFollowUpPromptNotFoundError("Unknown reading follow-up prompt version")
    root = files("app.prompts").joinpath(version)
    try:
        return ReadingFollowUpPromptSet(
            version,
            *(
                root.joinpath(name).read_text("utf-8")
                for name in ("system.md", "request.md", "repair.md")
            ),
        )
    except (FileNotFoundError, ModuleNotFoundError) as error:
        raise ReadingFollowUpPromptNotFoundError(
            "Reading follow-up prompt resources unavailable"
        ) from error
