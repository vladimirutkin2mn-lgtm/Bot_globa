"""Central product identity independent from the legacy relationship domain."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProductIdentity:
    """Stable repository and runtime identity for the evolving product."""

    repository_slug: str
    consumer_brand: str
    working_name: str
    api_title: str
    version: str
    legacy_baseline_name: str


PRODUCT_IDENTITY = ProductIdentity(
    repository_slug="bot_globa",
    consumer_brand="Numa",
    working_name="Персональный AI-оракул",
    api_title="Bot Globa API",
    version="0.1.0",
    legacy_baseline_name="HeartSignal",
)
