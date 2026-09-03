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
    return parser.parse_args()


def _reserved_upper_bound_usd(reserved_microusd_per_reading: int) -> float:
    if reserved_microusd_per_reading <= 0:
        raise ValueError(
            "ORACLE_MAX_RESERVED_COST_MICROUSD_PER_READING must be positive "
            "before paid autoresearch can run"
        )
    return len(ORACLE_RESEARCH_CASES) * reserved_microusd_per_reading / 1_000_000


async def _run(max_budget_usd: float) -> dict[str, object]:
    if max_budget_usd <= 0:
        raise ValueError("max budget must be positive")

    settings = get_settings()
    observability = get_observability_settings()
    release = get_oracle_release_settings()

    if settings.llm_provider != "openai":
        raise ValueError("production LLM autoresearch currently requires the OpenAI adapter")
    if not settings.llm_model.strip():
        raise ValueError("LLM_MODEL must be configured")
    if (
        observability.llm_input_cost_usd_per_million_tokens is None
        or observability.llm_output_cost_usd_per_million_tokens is None
    ):
        raise ValueError("production LLM token rates must be configured")

    reserved_upper_bound = _reserved_upper_bound_usd(
        release.oracle_max_reserved_cost_microusd_per_reading
    )
    if reserved_upper_bound > max_budget_usd:
        raise ValueError(
            "reserved autoresearch upper bound exceeds max budget: "
            f"{reserved_upper_bound:.6f} > {max_budget_usd:.6f} USD"
        )

    raw = create_llm_client(settings)
    llm = wrap_llm_with_langsmith(raw, observability)
    try:
        evaluation = await evaluate_oracle_llm(
            llm,
            prompt_source="production",
            provider=settings.llm_provider,
            model=settings.llm_model,
            input_cost_usd_per_million=(
                observability.llm_input_cost_usd_per_million_tokens
            ),
            output_cost_usd_per_million=(
                observability.llm_output_cost_usd_per_million_tokens
            ),
        )
    finally:
        await close_llm_client(llm)

    return {
        "reserved_upper_bound_usd": round(reserved_upper_bound, 6),
        "max_budget_usd": round(max_budget_usd, 6),
        "evaluation": evaluation.payload(),
    }


def main() -> None:
    args = _parse_args()
    payload = asyncio.run(_run(float(args.max_budget_usd)))
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
