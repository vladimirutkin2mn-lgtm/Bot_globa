"""Run Numa LLM autoresearch against the fixed synthetic dataset."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import cast

from app.observability.langsmith import wrap_llm_with_langsmith
from app.observability.settings import ObservabilitySettings
from app.providers.llm.base import LLMClient, close_llm_client
from app.providers.llm.openai import OpenAILLMClient
from app.research.oracle_llm_evaluator import (
    OracleResearchCaseEvaluation,
    OracleResearchComparison,
    OracleResearchEvaluation,
    PromptSource,
    evaluate_oracle_llm,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate Numa prompt/model research.")
    parser.add_argument(
        "--prompt-source",
        choices=("production", "candidate"),
        default="candidate",
    )
    parser.add_argument("--model", default=os.getenv("LLM_MODEL", ""))
    parser.add_argument("--base-url", default=os.getenv("LLM_BASE_URL", ""))
    parser.add_argument("--provider", default="openai")
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    parser.add_argument("--transport-attempts", type=int, default=2)
    parser.add_argument("--input-cost-usd-per-million", type=float)
    parser.add_argument("--output-cost-usd-per-million", type=float)
    parser.add_argument("--baseline-report")
    parser.add_argument("--output-dir", default="autoresearch-artifacts/oracle-llm")
    return parser.parse_args()


def _load_baseline(path: str) -> OracleResearchEvaluation:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("baseline report must contain one JSON object")
    cases_payload = payload.get("cases")
    if not isinstance(cases_payload, list):
        raise ValueError("baseline report is missing cases")

    cases = tuple(
        OracleResearchCaseEvaluation(
            case_id=str(item["case_id"]),
            persona_code=str(item["persona_code"]),
            numa_score=float(item["numa_score"]),
            hard_gates={str(key): bool(value) for key, value in item["hard_gates"].items()},
            repair_used=bool(item["repair_used"]),
            attempts=int(item["attempts"]),
            input_tokens=int(item["input_tokens"]),
            output_tokens=int(item["output_tokens"]),
            latency_ms=int(item["latency_ms"]),
            failure_code=None if item["failure_code"] is None else str(item["failure_code"]),
            metrics={str(key): float(value) for key, value in item["metrics"].items()},
        )
        for item in cases_payload
        if isinstance(item, dict)
    )
    return OracleResearchEvaluation(
        dataset_version=str(payload["dataset_version"]),
        prompt_source=cast("PromptSource", str(payload["prompt_source"])),
        prompt_coordinate=str(payload["prompt_coordinate"]),
        provider=str(payload["provider"]),
        model=str(payload["model"]),
        numa_score=float(payload["numa_score"]),
        quality_score=float(payload["quality_score"]),
        gates_passed=bool(payload["gates_passed"]),
        repair_rate=float(payload["repair_rate"]),
        input_tokens=int(payload["input_tokens"]),
        output_tokens=int(payload["output_tokens"]),
        latency_ms=int(payload["latency_ms"]),
        estimated_cost_usd=(
            None if payload["estimated_cost_usd"] is None else float(payload["estimated_cost_usd"])
        ),
        cases=cases,
    )


def _comparison(
    candidate: OracleResearchEvaluation,
    baseline: OracleResearchEvaluation,
) -> OracleResearchComparison:
    if candidate.dataset_version != baseline.dataset_version:
        raise ValueError("candidate and baseline dataset versions differ")
    if candidate.provider != baseline.provider or candidate.model != baseline.model:
        raise ValueError("candidate and baseline must use the same provider/model")
    return OracleResearchComparison(candidate=candidate, baseline=baseline)


def _markdown(
    evaluation: OracleResearchEvaluation,
    comparison: OracleResearchComparison | None,
) -> str:
    lines = [
        "# Numa Autoresearch · LLM",
        "",
        f"**Prompt source:** {evaluation.prompt_source}",
        f"**Prompt coordinate:** {evaluation.prompt_coordinate}",
        f"**Model:** {evaluation.provider}:{evaluation.model}",
        f"**Numa score:** {evaluation.numa_score:.4f}",
        f"**Quality score:** {evaluation.quality_score:.4f}",
        f"**All hard gates passed:** {evaluation.gates_passed}",
        f"**Repair rate:** {evaluation.repair_rate:.2%}",
        f"**Input tokens:** {evaluation.input_tokens}",
        f"**Output tokens:** {evaluation.output_tokens}",
        f"**Latency:** {evaluation.latency_ms} ms",
        (
            "**Estimated cost:** unknown"
            if evaluation.estimated_cost_usd is None
            else f"**Estimated cost:** USD {evaluation.estimated_cost_usd:.6f}"
        ),
        "",
        "| Case | Persona | Score | Gates | Repair |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for case in evaluation.cases:
        lines.append(
            f"| {case.case_id} | {case.persona_code} | {case.numa_score:.2f} | "
            f"{'✅' if case.gates_passed else '❌'} | {'yes' if case.repair_used else 'no'} |"
        )
    if comparison is not None:
        beats_baseline = str(
            comparison.candidate.gates_passed and comparison.quality_delta > 0
        ).lower()
        lines.extend(
            (
                "",
                "## Baseline comparison",
                "",
                f"- quality delta: {comparison.quality_delta:+.4f}",
                f"- latency delta: {comparison.latency_delta_ms:+d} ms",
                (
                    "- cost delta: unknown"
                    if comparison.cost_delta_usd is None
                    else f"- cost delta: USD {comparison.cost_delta_usd:+.6f}"
                ),
                f"- candidate beats baseline: {beats_baseline}",
            )
        )
    lines.append("")
    return "\n".join(lines)


async def _run() -> None:
    args = _parse_args()
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise ValueError("OPENAI_API_KEY is required for live LLM autoresearch")
    model = str(args.model).strip()
    if not model:
        raise ValueError("--model or LLM_MODEL is required")

    raw: LLMClient = OpenAILLMClient(
        key,
        model,
        float(args.timeout_seconds),
        int(args.transport_attempts),
        base_url=str(args.base_url).strip() or None,
    )
    observed = wrap_llm_with_langsmith(raw, ObservabilitySettings())
    try:
        evaluation = await evaluate_oracle_llm(
            observed,
            prompt_source=cast("PromptSource", str(args.prompt_source)),
            provider=str(args.provider),
            model=model,
            input_cost_usd_per_million=args.input_cost_usd_per_million,
            output_cost_usd_per_million=args.output_cost_usd_per_million,
        )
    finally:
        await close_llm_client(observed)

    comparison = (
        None
        if not args.baseline_report
        else _comparison(evaluation, _load_baseline(str(args.baseline_report)))
    )
    output_dir = Path(str(args.output_dir))
    payload = evaluation.payload()
    markdown = _markdown(evaluation, comparison)
    await asyncio.to_thread(_write_reports, output_dir, payload, markdown)

    print(f"numa_score: {evaluation.numa_score:.4f}")
    print(f"quality_score: {evaluation.quality_score:.4f}")
    print(f"gates_passed: {str(evaluation.gates_passed).lower()}")
    print(f"repair_rate: {evaluation.repair_rate:.4f}")
    print(
        "estimated_cost_usd: "
        + (
            "unknown"
            if evaluation.estimated_cost_usd is None
            else f"{evaluation.estimated_cost_usd:.8f}"
        )
    )
    if comparison is not None:
        print(f"quality_delta: {comparison.quality_delta:+.4f}")
        print(
            "cost_delta_usd: "
            + (
                "unknown"
                if comparison.cost_delta_usd is None
                else f"{comparison.cost_delta_usd:+.8f}"
            )
        )
    print("---")
    print(markdown)


def _write_reports(
    output_dir: Path,
    payload: dict[str, object],
    markdown: str,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "oracle-llm-autoresearch.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "oracle-llm-autoresearch.md").write_text(markdown, encoding="utf-8")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
