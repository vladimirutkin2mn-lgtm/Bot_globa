"""Trim what only affects layout, so it cannot discard a whole reading.

The structured contract mixes two kinds of rule. Some protect meaning: a reading may only
name the symbols the engine drew, in the positions it drew them. Others protect layout and
cost: how long a sentence may be, how many scenarios fit a Telegram message. Breaking the
first makes the answer wrong; breaking the second makes it longer than planned.

Both used to end the same way — the reading was thrown away and the user was told it could
not be completed, because a sentence ran a hundred characters over. This module takes the
second kind out of that path: overflow is trimmed and the reading is delivered. The first
kind is untouched and still fails validation.

Limits are read from the JSON schema of the model itself, so they cannot drift from what
is enforced a moment later, and only upper bounds are applied — a missing item cannot be
invented, so `minItems` and `minLength` remain real errors.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

ELLIPSIS = "…"


def clamp_presentation(payload: Any, schema: dict[str, Any]) -> Any:
    """Return the payload with over-long text and over-full lists cut to their limits."""

    trimmed: list[str] = []
    result = _clamp(payload, schema, schema, (), trimmed)
    if trimmed:
        # Field paths only: what overflowed is the model's wording, never logged.
        logger.info("reading_presentation_trimmed fields=%s", ",".join(sorted(set(trimmed))))
    return result


def _clamp(
    value: Any,
    node: dict[str, Any],
    root: dict[str, Any],
    path: tuple[str, ...],
    trimmed: list[str],
) -> Any:
    node = _resolve(node, root)
    if isinstance(value, str):
        return _clamp_text(value, node, path, trimmed)
    if isinstance(value, list):
        return _clamp_items(value, node, root, path, trimmed)
    if isinstance(value, dict):
        properties = node.get("properties")
        if not isinstance(properties, dict):
            return value
        return {
            key: (
                _clamp(item, properties[key], root, (*path, key), trimmed)
                if isinstance(properties.get(key), dict)
                else item
            )
            for key, item in value.items()
        }
    return value


def _clamp_text(value: str, node: dict[str, Any], path: tuple[str, ...], trimmed: list[str]) -> str:
    maximum = node.get("maxLength")
    if not isinstance(maximum, int) or len(value) <= maximum:
        return value
    trimmed.append(".".join(path) or "(root)")
    return _shortened(value, maximum)


def _clamp_items(
    value: list[Any],
    node: dict[str, Any],
    root: dict[str, Any],
    path: tuple[str, ...],
    trimmed: list[str],
) -> list[Any]:
    items = node.get("items")
    kept = value
    maximum = node.get("maxItems")
    if isinstance(maximum, int) and len(value) > maximum:
        trimmed.append(".".join(path) or "(root)")
        # The earlier entries are the ones the model led with, so the tail is what goes.
        kept = value[:maximum]
    if not isinstance(items, dict):
        return kept
    return [_clamp(item, items, root, (*path, "[]"), trimmed) for item in kept]


def _resolve(node: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    """Follow a `$ref` so nested models carry their own limits."""

    reference = node.get("$ref")
    if not isinstance(reference, str) or not reference.startswith("#/$defs/"):
        return node
    target = root.get("$defs", {}).get(reference.removeprefix("#/$defs/"))
    return target if isinstance(target, dict) else node


def _shortened(value: str, maximum: int) -> str:
    """Cut at a word boundary so a trimmed sentence still reads as one."""

    if maximum <= len(ELLIPSIS):
        return value[:maximum]
    head = value[: maximum - len(ELLIPSIS)].rstrip()
    spaced = head.rsplit(" ", 1)
    if len(spaced) == 2 and len(spaced[0]) >= maximum // 2:
        head = spaced[0]
    return head.rstrip(" ,.;:—-") + ELLIPSIS
