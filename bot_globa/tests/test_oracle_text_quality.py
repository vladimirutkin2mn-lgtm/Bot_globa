from app.domain.reading import SymbolOrientation
from app.domain.reading_result import (
    ReadingResult,
    ReadingSafetyAssessment,
    ReadingScenario,
    ReadingSymbolResult,
    ShareCardPayload,
)
from app.services.oracle_text_quality import evaluate_reading_editorial_quality


def _reading(*, repeated: bool) -> ReadingResult:
    repeated_line = "Сейчас важно спокойно назвать границы и не торопиться."
    return ReadingResult(
        title=repeated_line if repeated else "Разговор важнее догадок",
        opening=repeated_line if repeated else "Неопределённость держится на недосказанности.",
        symbols=[
            ReadingSymbolResult(
                symbol_id="card-1",
                position="present",
                orientation=SymbolOrientation.UPRIGHT,
                interpretation="Карта подчёркивает необходимость проверить ожидания действиями.",
            )
        ],
        patterns=[repeated_line if repeated else "Ожидание ответа усиливает внутреннее напряжение."],
        possible_scenarios=[
            ReadingScenario(
                scenario="Разговор проясняет позицию обеих сторон.",
                conditions=["Вопрос задан прямо и без давления."],
            )
        ],
        reflection_questions=["Какой ответ вы готовы услышать без попытки его изменить?"],
        practical_step=repeated_line if repeated else "Задайте один прямой вопрос и оцените ответ по действию.",
        uncertainty_note="Это интерпретация, а не знание чужих мыслей.",
        share_card=ShareCardPayload(
            headline=repeated_line if repeated else "Ясность начинается с одного прямого вопроса",
            short_text=repeated_line if repeated else "Не додумывайте то, что можно проверить разговором.",
        ),
        safety=ReadingSafetyAssessment(high_risk_detected=False, categories=[]),
    )


def test_editorial_quality_flags_redundant_reading() -> None:
    quality = evaluate_reading_editorial_quality(_reading(repeated=True))

    assert quality.needs_editorial_review is True


def test_editorial_quality_does_not_flag_distinct_sections() -> None:
    quality = evaluate_reading_editorial_quality(_reading(repeated=False))

    assert quality.stock_phrase_hits < 2
    assert quality.max_section_similarity < 0.68
