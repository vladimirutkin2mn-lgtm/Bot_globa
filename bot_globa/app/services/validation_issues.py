"""Turn a schema rejection into something a repair attempt can act on.

Split out because both the reading and the horoscope validator need it, and because
what may be sent back to a model is a privacy decision worth stating once: the rule
and its limit, never the value that broke it.
"""

from pydantic import ValidationError


def describe_validation_issues(error: object) -> tuple[str, ...]:
    """Name the rule that was broken, not just the field that broke it.

    Pydantic error types and limits are our own contract, never the user's text, so they
    are safe to send back for a repair — and without them the retry is told
    `possible_scenarios.0.conditions.0:invalid` and has nothing to act on.
    """

    if not isinstance(error, ValidationError):
        return ()
    described: list[str] = []
    for issue in error.errors(include_input=False, include_url=False):
        location = ".".join(str(part) for part in issue["loc"]) or "(root)"
        limits = ", ".join(
            f"{name}={value}"
            for name, value in sorted((issue.get("ctx") or {}).items())
            if isinstance(value, int | float | str)
        )
        detail = f"{issue['type']}" + (f" ({limits})" if limits else "")
        described.append(f"{location}: {detail}")
    return tuple(described)
