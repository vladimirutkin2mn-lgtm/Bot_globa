"""Deterministic privacy-safe assignment for conversion experiments."""

from enum import StrEnum
from hashlib import blake2s
from uuid import UUID

CONVERSION_HOOK_EXPERIMENT = "conversion_hook_v1"
FREE_PREVIEW_EXPERIMENT = "free_preview_v1"


class ConversionHookVariant(StrEnum):
    """Stable experiment arms; values are warehouse-safe codes."""

    A = "a"
    B = "b"
    C = "c"


class FreePreviewVariant(StrEnum):
    """Old-vs-new first free-answer arms from the owner-approved product plan."""

    BASELINE = "baseline"
    COMPLETE = "complete"


_VARIANTS = tuple(ConversionHookVariant)
_FREE_PREVIEW_VARIANTS = tuple(FreePreviewVariant)


def conversion_hook_variant(user_id: UUID) -> ConversionHookVariant:
    """Assign one stable A/B/C arm from the internal user UUID only.

    UUIDv4's final byte is uniform, requires no database write and is straightforward to
    reproduce in PostgreSQL analytics transforms. 256 does not divide by three, so arm A
    draws 86/256 against 85/256 for B and C — a 0.4 pp tilt, far below the effect any
    launch experiment here is powered to detect, and worth naming rather than implying
    the split is exactly even.
    """

    return _VARIANTS[user_id.bytes[-1] % len(_VARIANTS)]


def free_preview_variant(user_id: UUID) -> FreePreviewVariant:
    """Assign a stable 50/50 preview arm independently from entry source and hook cohort.

    A keyed-by-name digest keeps this experiment independent from the legacy A/B/C hook
    byte split without storing a new assignment row or exposing any external identifier.
    """

    digest = blake2s(
        FREE_PREVIEW_EXPERIMENT.encode() + user_id.bytes,
        digest_size=1,
    ).digest()[0]
    return _FREE_PREVIEW_VARIANTS[digest % len(_FREE_PREVIEW_VARIANTS)]


def free_preview_experiment_assignment(user_id: UUID) -> str:
    """Warehouse-safe assignment code used by the typed Numa funnel."""

    return f"{FREE_PREVIEW_EXPERIMENT}:{free_preview_variant(user_id).value}"


def conversion_experiment_properties(user_id: UUID) -> dict[str, str]:
    """Return content-free experiment metadata for durable analytics payloads."""

    return {
        "experiment_key": CONVERSION_HOOK_EXPERIMENT,
        "experiment_variant": conversion_hook_variant(user_id).value,
    }
