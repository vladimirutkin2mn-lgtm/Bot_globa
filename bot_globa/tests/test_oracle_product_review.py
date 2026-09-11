"""Contracts for the offline human product-quality review packet."""

import pytest

from app.research.oracle_llm_dataset import ORACLE_RESEARCH_CASES
from app.research.oracle_product_review import (
    ORACLE_PRODUCT_REVIEW_VERSION,
    PRODUCT_REVIEW_DIMENSIONS,
    ProductReviewComparison,
    ProductReviewDimension,
    ProductReviewScores,
    build_product_review_packet,
)


def _scores(value: int) -> ProductReviewScores:
    return ProductReviewScores(
        specificity=value,
        situation_fit=value,
        clarity=value,
        memorable_image=value,
        useful_step=value,
        desire_to_continue=value,
    )


def test_review_dimensions_match_owner_approved_product_rubric() -> None:
    assert PRODUCT_REVIEW_DIMENSIONS == (
        ProductReviewDimension.SPECIFICITY,
        ProductReviewDimension.SITUATION_FIT,
        ProductReviewDimension.CLARITY,
        ProductReviewDimension.MEMORABLE_IMAGE,
        ProductReviewDimension.USEFUL_STEP,
        ProductReviewDimension.DESIRE_TO_CONTINUE,
    )


def test_review_scores_are_explicit_one_to_five_and_compare_without_hidden_weights() -> None:
    with pytest.raises(ValueError):
        _scores(0)
    with pytest.raises(ValueError):
        _scores(6)

    comparison = ProductReviewComparison(_scores(2), _scores(4))
    assert comparison.baseline.mean == 2.0
    assert comparison.candidate.mean == 4.0
    assert comparison.mean_delta == 2.0
    assert set(comparison.deltas().values()) == {2}


def test_packet_uses_fixed_synthetic_cases_and_never_invents_answers_or_scores() -> None:
    packet = build_product_review_packet()
    assert packet["review_version"] == ORACLE_PRODUCT_REVIEW_VERSION
    cases = packet["cases"]
    assert isinstance(cases, list)
    assert [case["case_id"] for case in cases] == [case.case_id for case in ORACLE_RESEARCH_CASES]

    for case in cases:
        assert case["baseline_answer"] is None
        assert case["candidate_answer"] is None
        assert set(case["baseline_scores"].values()) == {None}
        assert set(case["candidate_scores"].values()) == {None}
        assert case["reviewer_note"] is None


def test_packet_rejects_empty_dataset_instead_of_claiming_a_review() -> None:
    with pytest.raises(ValueError):
        build_product_review_packet(())
