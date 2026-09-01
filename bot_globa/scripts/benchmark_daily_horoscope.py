"""Fetch a small public reference sample and compare derived quality metrics with Numa.

Third-party horoscope text is processed in memory only. Reports contain aggregate metrics
and SHA-256 fingerprints, never the fetched copy itself.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo

import httpx

from app.domain.natal_chart import ZodiacSign
from app.services.daily_horoscope_benchmark import (
    BenchmarkForecast,
    BenchmarkSourceSummary,
    build_source_summary,
    compare_source_summaries,
    extract_orakul_general_forecast,
)
from app.services.daily_horoscope_editorial import build_editorial_daily_horoscope

ORAKUL_BASE_URL = "https://orakul.com"
ORAKUL_ROBOTS_URL = f"{ORAKUL_BASE_URL}/robots.txt"
USER_AGENT = "NumaDailyBenchmark/1.0"
MOSCOW = ZoneInfo("Europe/Moscow")

_ORAKUL_SLUGS: dict[ZodiacSign, str] = {
    ZodiacSign.ARIES: "aries",
    ZodiacSign.TAURUS: "taurus",
    ZodiacSign.GEMINI: "gemini",
    ZodiacSign.CANCER: "cancer",
    ZodiacSign.LEO: "lion",
    ZodiacSign.VIRGO: "virgo",
    ZodiacSign.LIBRA: "libra",
    ZodiacSign.SCORPIO: "scorpio",
    ZodiacSign.SAGITTARIUS: "sagittarius",
    ZodiacSign.CAPRICORN: "capricorn",
    ZodiacSign.AQUARIUS: "aquarius",
    ZodiacSign.PISCES: "pisces",
}


class BenchmarkFetchError(RuntimeError):
    """Reference source could not be fetched safely enough for benchmarking."""


def _build_url(sign: ZodiacSign, period: str) -> str:
    return (
        f"{ORAKUL_BASE_URL}/horoscope/astrologic/general/"
        f"{_ORAKUL_SLUGS[sign]}/{period}.html"
    )


async def _load_robots(client: httpx.AsyncClient) -> RobotFileParser:
    response = await client.get(ORAKUL_ROBOTS_URL)
    if response.status_code != httpx.codes.OK:
        raise BenchmarkFetchError(
            f"refusing benchmark because robots.txt returned HTTP {response.status_code}"
        )
    parser = RobotFileParser()
    parser.set_url(ORAKUL_ROBOTS_URL)
    parser.parse(response.text.splitlines())
    return parser


async def _fetch_orakul(period: str) -> list[BenchmarkForecast]:
    forecasts: list[BenchmarkForecast] = []
    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=httpx.Timeout(15.0),
    ) as client:
        robots = await _load_robots(client)
        for sign in ZodiacSign:
            url = _build_url(sign, period)
            if not robots.can_fetch(USER_AGENT, url):
                raise BenchmarkFetchError(f"robots.txt does not allow benchmark fetch: {url}")
            response = await client.get(url)
            if response.status_code != httpx.codes.OK:
                raise BenchmarkFetchError(
                    f"reference page returned HTTP {response.status_code}: {url}"
                )
            forecasts.append(
                BenchmarkForecast(
                    sign=sign,
                    text=extract_orakul_general_forecast(response.text),
                )
            )
            # Twelve requests once a day are enough. Keep the reference load deliberately low.
            await asyncio.sleep(0.5)
    return forecasts


def _period_date(period: str, today: date) -> date:
    if period == "yesterday":
        return today - timedelta(days=1)
    if period == "tomorrow":
        return today + timedelta(days=1)
    if period == "today":
        return today
    raise ValueError(f"unsupported benchmark period: {period}")


def _numa_forecasts(forecast_date: date) -> list[BenchmarkForecast]:
    snapshot = build_editorial_daily_horoscope(forecast_date)
    return [BenchmarkForecast(sign=item.sign, text=item.text) for item in snapshot.signs]


def _render_markdown(
    run_date: date,
    period: str,
    numa: BenchmarkSourceSummary,
    reference: BenchmarkSourceSummary,
    comparison: dict[str, object],
) -> str:
    n = numa.metrics
    r = reference.metrics
    signals = comparison.get("signals")
    signal_lines = (
        [f"- {item}" for item in signals if isinstance(item, str)]
        if isinstance(signals, list)
        else ["- Benchmark produced no signal list."]
    )
    return "\n".join(
        [
            "# Daily horoscope benchmark",
            "",
            f"Run date: **{run_date.isoformat()}**  ",
            f"Period: **{period}**  ",
            "Reference: **Orakul general daily horoscope**",
            "",
            "The report stores only derived metrics and one-way hashes, not reference copy.",
            "",
            "| Metric | Numa | Orakul |",
            "| --- | ---: | ---: |",
            f"| Avg words / sign | {n.avg_words:.1f} | {r.avg_words:.1f} |",
            f"| Avg sentences / sign | {n.avg_sentences:.1f} | {r.avg_sentences:.1f} |",
            f"| Cross-sign lexical diversity | {n.lexical_diversity:.1%} | {r.lexical_diversity:.1%} |",
            f"| Unique openings | {n.unique_opening_ratio:.1%} | {r.unique_opening_ratio:.1%} |",
            f"| Topic coverage | {n.topic_coverage_ratio:.1%} | {r.topic_coverage_ratio:.1%} |",
            f"| Distinct topics | {n.topic_variety} | {r.topic_variety} |",
            f"| Actionable next-step ratio | {n.actionable_ratio:.1%} | {r.actionable_ratio:.1%} |",
            "",
            "## Signals",
            "",
            *signal_lines,
            "",
            "## Interpretation",
            "",
            "This is a quality reference, not a source of copy. A gap can inform future Numa",
            "editorial changes, but no reference sentence is passed into Numa generation.",
            "",
        ]
    )


async def _run(period: str, output_dir: Path) -> None:
    today = datetime.now(MOSCOW).date()
    forecast_date = _period_date(period, today)

    numa = build_source_summary("numa", _numa_forecasts(forecast_date))
    orakul_forecasts = await _fetch_orakul(period)
    reference = build_source_summary("orakul", orakul_forecasts)
    comparison = compare_source_summaries(numa, reference)

    payload: dict[str, object] = {
        "schema_version": 1,
        "run_date": today.isoformat(),
        "forecast_date": forecast_date.isoformat(),
        "period": period,
        "reference": {
            "name": "Orakul",
            "url_template": (
                "https://orakul.com/horoscope/astrologic/general/{sign}/{period}.html"
            ),
            "copy_persisted": False,
        },
        "benchmark": comparison,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "daily-horoscope-benchmark.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "daily-horoscope-benchmark.md").write_text(
        _render_markdown(today, period, numa, reference, comparison),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare Numa daily-horoscope quality metrics with a public reference."
    )
    parser.add_argument(
        "--period",
        choices=("yesterday", "today", "tomorrow"),
        default="today",
    )
    parser.add_argument(
        "--output-dir",
        default="benchmark-artifacts",
    )
    args = parser.parse_args()
    asyncio.run(_run(str(args.period), Path(str(args.output_dir))))


if __name__ == "__main__":
    main()
