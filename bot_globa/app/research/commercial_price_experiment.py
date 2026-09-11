"""Fail-closed scaffold for a future owner-supplied commercial price experiment.

Nothing in this module changes BillingCatalog, checkout routing or current test prices.
It only defines a configuration template and an offline report shape for a later launch task.
"""

from dataclasses import dataclass

from app.domain.products import READING_PURCHASE_CODES

COMMERCIAL_PRICE_EXPERIMENT_VERSION = "commercial-price-test-v1"

_MARKETS = (
    ("ru", "RUB"),
    ("international", "EUR"),
    ("international", "USD"),
    ("telegram", "XTR"),
)


@dataclass(frozen=True, slots=True)
class CommercialPriceObservation:
    """Aggregate arm metrics; unknown costs remain unknown instead of becoming zero."""

    exposures: int
    checkout_started: int
    purchases: int
    gross_revenue_minor: int
    refunds_minor: int
    known_provider_fees_minor: int | None = None
    known_variable_cost_minor: int | None = None

    def __post_init__(self) -> None:
        values = (
            self.exposures,
            self.checkout_started,
            self.purchases,
            self.gross_revenue_minor,
            self.refunds_minor,
        )
        if any(value < 0 for value in values):
            raise ValueError("commercial price metrics cannot be negative")
        for value in (self.known_provider_fees_minor, self.known_variable_cost_minor):
            if value is not None and value < 0:
                raise ValueError("known commercial price costs cannot be negative")

    @property
    def checkout_conversion(self) -> float | None:
        if self.exposures == 0:
            return None
        return self.checkout_started / self.exposures

    @property
    def purchase_conversion(self) -> float | None:
        if self.exposures == 0:
            return None
        return self.purchases / self.exposures

    @property
    def net_contribution_minor(self) -> int | None:
        if self.known_provider_fees_minor is None or self.known_variable_cost_minor is None:
            return None
        return (
            self.gross_revenue_minor
            - self.refunds_minor
            - self.known_provider_fees_minor
            - self.known_variable_cost_minor
        )

    def payload(self) -> dict[str, int | float | None]:
        return {
            "exposures": self.exposures,
            "checkout_started": self.checkout_started,
            "purchases": self.purchases,
            "checkout_conversion": self.checkout_conversion,
            "purchase_conversion": self.purchase_conversion,
            "gross_revenue_minor": self.gross_revenue_minor,
            "refunds_minor": self.refunds_minor,
            "known_provider_fees_minor": self.known_provider_fees_minor,
            "known_variable_cost_minor": self.known_variable_cost_minor,
            "net_contribution_minor": self.net_contribution_minor,
        }


def build_commercial_price_experiment_template() -> dict[str, object]:
    """Return a disabled template with no invented candidate prices."""

    coordinates = [
        {
            "product_code": product_code.value,
            "market": market,
            "currency": currency,
            "baseline_source": "BillingCatalog/settings at experiment start",
            "candidate_amount_minor": None,
        }
        for product_code in READING_PURCHASE_CODES
        for market, currency in _MARKETS
    ]
    return {
        "experiment_version": COMMERCIAL_PRICE_EXPERIMENT_VERSION,
        "enabled": False,
        "activation": "separate_owner_approved_launch_task_only",
        "assignment": None,
        "coordinates": coordinates,
        "guardrails": {
            "current_catalog_unchanged": True,
            "owner_supplies_candidate_prices": True,
            "do_not_mix_with_text_or_frequency_test": True,
            "unknown_costs_remain_null": True,
        },
        "report_dimensions": [
            "product_code",
            "market",
            "currency",
            "arm",
            "entry_source",
        ],
        "report_metrics": [
            "exposures",
            "checkout_started",
            "purchases",
            "checkout_conversion",
            "purchase_conversion",
            "gross_revenue_minor",
            "refunds_minor",
            "known_provider_fees_minor",
            "known_variable_cost_minor",
            "net_contribution_minor",
        ],
    }
