"""Deterministic privacy-safe assignment for conversion-hook experiments."""

from enum import StrEnum
from uuid import UUID

CONVERSION_HOOK_EXPERIMENT = "conversion_hook_v1"


class ConversionHookVariant(StrEnum):
    """Stable experiment arms; values are warehouse-safe codes."""

    A = "a"
    B = "b"
    C = "c"


_VARIANTS = tuple(ConversionHookVariant)


def conversion_hook_variant(user_id: UUID) -> ConversionHookVariant:
    """Assign one stable A/B/C arm from the internal user UUID only.

    UUIDv4's final byte is random enough for an even launch split, requires no database
    write and is straightforward to reproduce in PostgreSQL analytics transforms.
    """

    return _VARIANTS[user_id.bytes[-1] % len(_VARIANTS)]


def conversion_experiment_properties(user_id: UUID) -> dict[str, str]:
    """Return content-free experiment metadata for durable analytics payloads."""

    return {
        "experiment_key": CONVERSION_HOOK_EXPERIMENT,
        "experiment_variant": conversion_hook_variant(user_id).value,
    }
