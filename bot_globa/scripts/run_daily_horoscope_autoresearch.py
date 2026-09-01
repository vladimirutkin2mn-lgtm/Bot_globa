"""Run the fixed Numa daily-horoscope autoresearch evaluator."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.research.daily_horoscope_evaluator import evaluate_current_candidate


def _render_markdown(payload: dict[str, object]) -> str:
    candidate = payload["candidate"]
    baseline = payload["baseline"]
    if not isinstance(candidate, dict) or not isinstance(baseline, dict):
        raise TypeError("autoresearch payload is malformed")

    candidate_metrics = candidate["metrics"]
    baseline_metrics = baseline["metrics"]
    if not isinstance(candidate_metrics, dict) or not isinstance(baseline_metrics, dict):
        raise TypeError("autoresearch metrics payload is malformed")

    lines = [
        "# Numa Autoresearch · Daily Horoscope",
        "",
        f"**Candidate numa_score:** {candidate['numa_score']}",
        f"**Production baseline:** {baseline['numa_score']}",
        f"**Delta:** {payload['delta']}",
        f"**Candidate gates passed:** {candidate['gates_passed']}",
        "",
        "| Metric | Candidate | Baseline |",
        "| --- | ---: | ---: |",
    ]
    for key in (
        "actionable_ratio",
        "topic_coverage_ratio",
        "topic_variety",
        "topic_balance",
        "lexical_diversity",
        "unique_opening_ratio",
        "temporal_diversity",
        "distinct_text_ratio",
        "avg_words",
        "max_caption_chars",
    ):
        lines.append(f"| {key} | {candidate_metrics[key]} | {baseline_metrics[key]} |")

    lines.extend(("", "## Hard gates", ""))
    hard_gates = candidate["hard_gates"]
    if not isinstance(hard_gates, dict):
        raise TypeError("autoresearch hard gates payload is malformed")
    for name, passed in sorted(hard_gates.items()):
        lines.append(f"- {'✅' if passed else '❌'} {name}")

    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the Numa horoscope research candidate.")
    parser.add_argument("--output-dir", default="autoresearch-artifacts")
    args = parser.parse_args()

    comparison = evaluate_current_candidate()
    payload = comparison.payload()
    markdown = _render_markdown(payload)

    output_dir = Path(str(args.output_dir))
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "daily-horoscope-autoresearch.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "daily-horoscope-autoresearch.md").write_text(markdown, encoding="utf-8")

    print(f"numa_score: {comparison.candidate.numa_score:.4f}")
    print(f"baseline_score: {comparison.baseline.numa_score:.4f}")
    print(f"delta: {comparison.delta:+.4f}")
    print(f"gates_passed: {str(comparison.candidate.gates_passed).lower()}")
    print("---")
    print(markdown)


if __name__ == "__main__":
    main()
