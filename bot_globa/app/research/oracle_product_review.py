"""Human-review rubric for product quality on the fixed synthetic oracle dataset.

This module deliberately does not call an LLM and does not infer subjective product
quality from proxy heuristics. Reviewers score already-produced baseline/candidate answers
side by side; the packet contains synthetic questions only.
"""

from dataclasses import dataclass
from enum import StrEnum
from statistics import fmean

from app.research.oracle_llm_dataset import ORACLE_RESEARCH_CASES, OracleResearchCase

ORACLE_PRODUCT_REVIEW_VERSION = "oracle-product-review-v1"


class ProductReviewDimension(StrEnum):
    SPECIFICITY = "specificity"
    SITUATION_FIT = "situation_fit"
    CLARITY = "clarity"
    MEMORABLE_IMAGE = "memorable_image"
    USEFUL_STEP = "useful_step"
    DESIRE_TO_CONTINUE = "desire_to_continue"


PRODUCT_REVIEW_DIMENSIONS = tuple(ProductReviewDimension)

_DIMENSION_LABELS: dict[ProductReviewDimension, str] = {
    ProductReviewDimension.SPECIFICITY: "Конкретность",
    ProductReviewDimension.SITUATION_FIT: "Попадание в ситуацию",
    ProductReviewDimension.CLARITY: "Понятность",
    ProductReviewDimension.MEMORABLE_IMAGE: "Запоминающийся образ",
    ProductReviewDimension.USEFUL_STEP: "Полезный следующий шаг",
    ProductReviewDimension.DESIRE_TO_CONTINUE: "Хочется продолжить",
}


@dataclass(frozen=True, slots=True)
class ProductReviewScores:
    """One human rating set; every dimension uses the same explicit 1–5 scale."""

    specificity: int
    situation_fit: int
    clarity: int
    memorable_image: int
    useful_step: int
    desire_to_continue: int

    def __post_init__(self) -> None:
        for dimension, score in self.values().items():
            if not 1 <= score <= 5:
                raise ValueError(f"{dimension.value} review score must be between 1 and 5")

    def values(self) -> dict[ProductReviewDimension, int]:
        return {
            ProductReviewDimension.SPECIFICITY: self.specificity,
            ProductReviewDimension.SITUATION_FIT: self.situation_fit,
            ProductReviewDimension.CLARITY: self.clarity,
            ProductReviewDimension.MEMORABLE_IMAGE: self.memorable_image,
            ProductReviewDimension.USEFUL_STEP: self.useful_step,
            ProductReviewDimension.DESIRE_TO_CONTINUE: self.desire_to_continue,
        }

    @property
    def mean(self) -> float:
        return fmean(self.values().values())

    def payload(self) -> dict[str, int]:
        return {dimension.value: score for dimension, score in self.values().items()}


@dataclass(frozen=True, slots=True)
class ProductReviewComparison:
    baseline: ProductReviewScores
    candidate: ProductReviewScores

    def deltas(self) -> dict[ProductReviewDimension, int]:
        baseline = self.baseline.values()
        candidate = self.candidate.values()
        return {dimension: candidate[dimension] - baseline[dimension] for dimension in PRODUCT_REVIEW_DIMENSIONS}

    @property
    def mean_delta(self) -> float:
        return self.candidate.mean - self.baseline.mean

    def payload(self) -> dict[str, object]:
        return {
            "baseline": self.baseline.payload(),
            "candidate": self.candidate.payload(),
            "deltas": {dimension.value: delta for dimension, delta in self.deltas().items()},
            "baseline_mean": round(self.baseline.mean, 4),
            "candidate_mean": round(self.candidate.mean, 4),
            "mean_delta": round(self.mean_delta, 4),
        }


def build_product_review_packet(
    cases: tuple[OracleResearchCase, ...] = ORACLE_RESEARCH_CASES,
) -> dict[str, object]:
    """Build a review template without generating or inventing either answer."""

    if not cases:
        raise ValueError("product review packet requires at least one synthetic case")
    return {
        "review_version": ORACLE_PRODUCT_REVIEW_VERSION,
        "scale": {
            "minimum": 1,
            "maximum": 5,
            "instruction": (
                "Оцените baseline и candidate независимо: 1 — критерий почти не выполнен, "
                "5 — выполнен очень хорошо. Не оценивайте цену или визуальный стиль здесь."
            ),
        },
        "dimensions": [
            {"code": dimension.value, "label": _DIMENSION_LABELS[dimension]}
            for dimension in PRODUCT_REVIEW_DIMENSIONS
        ],
        "cases": [_review_case(case) for case in cases],
    }


def _review_case(case: OracleResearchCase) -> dict[str, object]:
    empty_scores = {dimension.value: None for dimension in PRODUCT_REVIEW_DIMENSIONS}
    return {
        "case_id": case.case_id,
        "persona_code": case.persona_code,
        "topic": case.topic,
        "question": case.question,
        "context": case.context,
        "baseline_answer": None,
        "candidate_answer": None,
        "baseline_scores": dict(empty_scores),
        "candidate_scores": dict(empty_scores),
        "reviewer_note": None,
    }
