"""Run one privacy-safe Numa LLM baseline using the deployed runtime configuration."""

from __future__ import annotations

import argparse
import asyncio
import json

from app.config import get_settings
from app.observability.langsmith import wrap_llm_with_langsmith
from app.observability.settings import get_observability_settings
from app.providers.llm.base import close_llm_client
from app.providers.llm.factory import create_llm_client
from app.release_settings import get_oracle_release_settings
from app.research.oracle_llm_dataset import ORACLE_RESEARCH_CASES
from app.research.oracle_llm_evaluator import evaluate_oracle_llm


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one fixed-dataset Numa LLM production baseline."
    )
    parser.add_argument(
        "--max-budget-usd",
        type=float,
        default=1.0,
        help="Refuse before any provider call when the reserved upper bound exceeds this amount.",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Print safe runtime coordinates and budget readiness without calling the LLM.",
    )
    return parser.parse_args()


def _reserved_upper_bound_usd(reserved_microusd_per_reading: int) -> float:
    if reserved_microusd_per_reading <= 0:
        raise ValueError(
            "ORACLE_MAX_RESERVED_COST_MICROUSD_PER_READING must be positive "
            "before paid autoresearch can run"
        )
    return len(ORACLE_RESEARCH_CASES) * reserved_microusd_per_reading / 1_000_000


def _preflight(max_budget_usd: float) -> dict[str, object]:
    if max_budget_usd <= 0:
        raise ValueError("max budget must be positive")

    settings = get_settings()
    observability = get_observability_settings()
    release = get_oracle_release_settings()
    reasons: list[str] = []

    if settings.llm_provider != "openai":
        reasons.append("unsupported_provider")
    if not settings.llm_model.strip():
        reasons.append("model_unconfigured")
    input_rate = observability.llm_input_cost_usd_per_million_tokens
    output_rate = observability.llm_output_cost_usd_per_million_tokens
    if input_rate is None or output_rate is None:
        reasons.append("token_rates_unconfigured")

    reservation = release.oracle_max_reserved_cost_microusd_per_reading
    reserved_upper_bound: float | None = None
    if reservation <= 0:
        reasons.append("reserved_cost_unconfigured")
    else:
        reserved_upper_bound = _reserved_upper_bound_usd(reservation)
        if reserved_upper_bound > max_budget_usd:
            reasons.append("reserved_upper_bound_exceeds_budget")

    return {
        "provider": settings.llm_provider,
        "model": settings.llm_model,
        "input_cost_usd_per_million_tokens": input_rate,
        "output_cost_usd_per_million_tokens": output_rate,
        "reserved_cost_microusd_per_reading": reservation,
        "reserved_upper_bound_usd": (
            None if reserved_upper_bound is None else round(reserved_upper_bound, 6)
        ),
        "max_budget_usd": round(max_budget_usd, 6),
        "dataset_cases": len(ORACLE_RESEARCH_CASES),
        "can_run_paid_baseline": not reasons,
        "blocking_reasons": reasons,
    }


async def _run(max_budget_usd: float) -> dict[str, object]:
    preflight = _preflight(max_budget_usd)
    if not bool(preflight["can_run_paid_baseline"]):
        blocking_reasons = preflight["blocking_reasons"]
        if not isinstance(blocking_reasons, list):
            raise TypeError("preflight blocking reasons are malformed")
        reasons = ",".join(str(value) for value in blocking_reasons)
        raise ValueError(f"paid baseline preflight failed: {reasons}")

    settings = get_settings()
    observability = get_observability_settings()
    input_rate = observability.llm_input_cost_usd_per_million_tokens
    output_rate = observability.llm_output_cost_usd_per_million_tokens
    assert input_rate is not None and output_rate is not None

    raw = create_llm_client(settings)
    llm = wrap_llm_with_langsmith(raw, observability)
    try:
        evaluation = await evaluate_oracle_llm(
            llm,
            prompt_source="production",
            provider=settings.llm_provider,
            model=settings.llm_model,
            input_cost_usd_per_million=input_rate,
            output_cost_usd_per_million=output_rate,
        )
    finally:
        await close_llm_client(llm)

    return {
        "preflight": preflight,
        "evaluation": evaluation.payload(),
    }


def main() -> None:
    args = _parse_args()
    max_budget_usd = float(args.max_budget_usd)
    payload = (
        _preflight(max_budget_usd)
        if bool(args.preflight_only)
        else asyncio.run(_run(max_budget_usd))
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
