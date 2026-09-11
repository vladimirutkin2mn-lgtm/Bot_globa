"""Offline contracts for the future commercial-price experiment scaffold."""

from app.research.commercial_price_experiment import (
    COMMERCIAL_PRICE_EXPERIMENT_VERSION,
    CommercialPriceObservation,
    build_commercial_price_experiment_template,
)


def test_commercial_price_template_is_disabled_and_contains_no_candidate_prices() -> None:
    template = build_commercial_price_experiment_template()

    assert template["experiment_version"] == COMMERCIAL_PRICE_EXPERIMENT_VERSION
    assert template["enabled"] is False
    assert template["assignment"] is None
    coordinates = template["coordinates"]
    assert isinstance(coordinates, list)
    assert coordinates
    assert all(coordinate["candidate_amount_minor"] is None for coordinate in coordinates)
    assert all(
        coordinate["baseline_source"] == "BillingCatalog/settings at experiment start"
        for coordinate in coordinates
    )


def test_template_keeps_source_separate_and_blocks_mixed_product_tests() -> None:
    template = build_commercial_price_experiment_template()

    report_dimensions = template["report_dimensions"]
    assert isinstance(report_dimensions, list)
    assert "entry_source" in report_dimensions

    guardrails = template["guardrails"]
    assert isinstance(guardrails, dict)
    assert guardrails["current_catalog_unchanged"] is True
    assert guardrails["owner_supplies_candidate_prices"] is True
    assert guardrails["do_not_mix_with_text_or_frequency_test"] is True


def test_unknown_commercial_costs_do_not_become_zero() -> None:
    observation = CommercialPriceObservation(
        exposures=100,
        checkout_started=20,
        purchases=10,
        gross_revenue_minor=10_000,
        refunds_minor=1_000,
    )

    assert observation.checkout_conversion == 0.2
    assert observation.purchase_conversion == 0.1
    assert observation.net_contribution_minor is None
    assert observation.payload()["net_contribution_minor"] is None


def test_net_contribution_uses_only_known_costs() -> None:
    observation = CommercialPriceObservation(
        exposures=100,
        checkout_started=20,
        purchases=10,
        gross_revenue_minor=10_000,
        refunds_minor=1_000,
        known_provider_fees_minor=500,
        known_variable_cost_minor=700,
    )

    assert observation.net_contribution_minor == 7_800


def test_commercial_price_observation_rejects_negative_metrics() -> None:
    try:
        CommercialPriceObservation(
            exposures=-1,
            checkout_started=0,
            purchases=0,
            gross_revenue_minor=0,
            refunds_minor=0,
        )
    except ValueError as exc:
        assert "cannot be negative" in str(exc)
    else:
        raise AssertionError("negative observations must fail closed")
