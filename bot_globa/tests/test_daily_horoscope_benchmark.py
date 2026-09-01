from app.domain.natal_chart import ZodiacSign
from app.services.daily_horoscope_benchmark import (
    BenchmarkForecast,
    build_benchmark_metrics,
    build_source_summary,
    compare_source_summaries,
    extract_orakul_general_forecast,
)


def test_extract_orakul_general_forecast_keeps_only_forecast_body() -> None:
    html = """
    <html>
      <head><style>.hidden { display: none; }</style></head>
      <body>
        <nav>Гороскопы</nav>
        <h1>Лев</h1>
        <h2>Общий гороскоп на сегодня, 1 сентября, 2026</h2>
        <p>В рабочем вопросе появится новый вариант.</p>
        <p>Сначала проверьте детали, а затем принимайте решение.</p>
        <a href="/more">Подробнее</a>
        <div>Хочу получать рассылку</div>
        <script>ignored_forecast_copy()</script>
      </body>
    </html>
    """

    result = extract_orakul_general_forecast(html)

    assert result == (
        "В рабочем вопросе появится новый вариант. "
        "Сначала проверьте детали, а затем принимайте решение."
    )
    assert "рассылку" not in result
    assert "ignored_forecast_copy" not in result


def test_extract_orakul_general_forecast_rejects_unexpected_page() -> None:
    html = "<html><body><h1>Нет прогноза</h1></body></html>"

    try:
        extract_orakul_general_forecast(html)
    except ValueError as error:
        assert "heading not found" in str(error)
    else:
        raise AssertionError("unexpected page must not be treated as a horoscope")


def test_benchmark_metrics_reward_cross_sign_variety() -> None:
    repeated = [
        BenchmarkForecast(ZodiacSign.ARIES, "Сегодня лучше проверить рабочий план."),
        BenchmarkForecast(ZodiacSign.TAURUS, "Сегодня лучше проверить рабочий план."),
        BenchmarkForecast(ZodiacSign.GEMINI, "Сегодня лучше проверить рабочий план."),
    ]
    varied = [
        BenchmarkForecast(ZodiacSign.ARIES, "На работе завершите важный проект."),
        BenchmarkForecast(ZodiacSign.TAURUS, "В любви честный разговор многое изменит."),
        BenchmarkForecast(ZodiacSign.GEMINI, "Поездка принесёт полезную новую информацию."),
    ]

    repeated_metrics = build_benchmark_metrics(repeated)
    varied_metrics = build_benchmark_metrics(varied)

    assert varied_metrics.lexical_diversity > repeated_metrics.lexical_diversity
    assert varied_metrics.unique_opening_ratio > repeated_metrics.unique_opening_ratio
    assert varied_metrics.topic_variety > repeated_metrics.topic_variety


def test_source_summary_persists_metrics_and_hashes_but_not_copy() -> None:
    source_text = "Секретный тестовый прогноз, который не должен попасть в payload."
    summary = build_source_summary(
        "reference",
        [BenchmarkForecast(ZodiacSign.LEO, source_text)],
    )

    payload = summary.payload()
    serialized = str(payload)

    assert source_text not in serialized
    assert payload["source"] == "reference"
    assert "fingerprints" in payload
    assert "metrics" in payload


def test_comparison_flags_material_length_and_topic_gap() -> None:
    numa = build_source_summary(
        "numa",
        [
            BenchmarkForecast(ZodiacSign.ARIES, "Выберите темп."),
            BenchmarkForecast(ZodiacSign.TAURUS, "Сделайте шаг."),
        ],
    )
    reference = build_source_summary(
        "reference",
        [
            BenchmarkForecast(
                ZodiacSign.ARIES,
                "На работе появится новая задача. Обсудите проект с коллегой и проверьте детали.",
            ),
            BenchmarkForecast(
                ZodiacSign.TAURUS,
                "В отношениях назревает разговор. Поговорите с партнёром и не спешите с выводами.",
            ),
        ],
    )

    result = compare_source_summaries(numa, reference)

    signals = result["signals"]
    assert isinstance(signals, list)
    assert "Numa forecasts are materially shorter than the reference." in signals
    assert "Numa covers fewer distinct life topics than the reference." in signals


def test_benchmark_recognizes_current_numa_action_verbs() -> None:
    forecasts = [
        BenchmarkForecast(ZodiacSign.ARIES, "Разговор изменит планы — задайте прямой вопрос."),
        BenchmarkForecast(ZodiacSign.TAURUS, "В переписке всплывёт нюанс — перечитайте детали."),
        BenchmarkForecast(ZodiacSign.GEMINI, "Карьерный вопрос сдвинется — инициируйте разговор."),
    ]

    assert build_benchmark_metrics(forecasts).actionable_ratio == 1.0


def test_benchmark_does_not_treat_strong_as_health_energy() -> None:
    forecasts = [
        BenchmarkForecast(
            ZodiacSign.ARIES,
            "Сильная позиция поможет сохранить спокойствие.",
        )
    ]

    metrics = build_benchmark_metrics(forecasts)

    assert metrics.topic_distribution == {"other": 1}


def test_benchmark_recognizes_additional_current_numa_action_verbs() -> None:
    forecasts = [
        BenchmarkForecast(
            ZodiacSign.ARIES,
            "Решение созреет быстро — не откладывайте шаг.",
        ),
        BenchmarkForecast(
            ZodiacSign.TAURUS,
            "Чужие финансовые ожидания давят — отделите обязательства.",
        ),
    ]

    metrics = build_benchmark_metrics(forecasts)

    assert metrics.actionable_ratio == 1.0
