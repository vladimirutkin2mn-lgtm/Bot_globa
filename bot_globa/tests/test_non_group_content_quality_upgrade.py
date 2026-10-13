import inspect
import json
from datetime import date
from pathlib import Path
from typing import cast

import pytest

from app.domain.natal_chart import ZodiacSign
from app.domain.persona import persona_definition
from app.prompts.horoscope import load_horoscope_prompts
from app.prompts.memory_extraction import (
    MEMORY_EXTRACTION_PROMPT_VERSION,
    load_memory_extraction_prompts,
)
from app.prompts.oracle import load_oracle_reading_prompts
from app.prompts.reading_followup import load_reading_followup_prompts
from app.providers.llm.base import LLMCompletion, LLMRequest
from app.services.daily_horoscope_ai import (
    DAILY_AI_METHOD_VERSION,
    DAILY_HOROSCOPE_PROMPT_VERSION,
    DailyHoroscopeAIEditor,
    InvalidDailyHoroscopeAIResultError,
)
from app.services.daily_horoscope_temporal_benchmark import (
    TemporalDailyItem,
    evaluate_temporal_daily,
)
from app.services.daily_sky import build_daily_horoscope
from app.services.oracle_editorial_quality import evaluate_editorial_quality
from app.services.personal_oracle_routing_benchmark import evaluate_routing
from app.services.reading_followup import ReadingFollowUpService


class FakeDailyLLM:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.request: LLMRequest | None = None

    async def generate_structured(self, request: LLMRequest) -> LLMCompletion:
        self.request = request
        return LLMCompletion(
            payload=json.dumps(self.payload, ensure_ascii=False),
            provider="test",
            model="test",
        )


def _daily_payload() -> dict[str, object]:
    texts = (
        "В переговорах появится деталь, которую лучше уточнить до ответа. "
        "Задайте один прямой вопрос.",
        "Денежная тема потребует аккуратности с условиями. "
        "Сверьте цифры до следующего шага.",
        "Домашний вопрос выйдет на первый план без предупреждения. "
        "Оставьте место для спокойного разговора.",
        "Рабочий темп может оказаться неровным. Закройте одну важную задачу прежде, "
        "чем брать новую.",
        "В личном общении станет заметнее чужая инициатива. "
        "Смотрите прежде всего на поступки.",
        "Новая информация способна поменять первоначальный план. "
        "Проверьте источник и только потом решайте.",
        "В карьере проявится возможность показать результат. "
        "Выберите один вклад, который стоит сделать заметнее.",
        "Разговор с другом поможет увидеть слабое место в плане. "
        "Возьмите из него одну практичную идею.",
        "Пауза сегодня окажется полезнее лишней спешки. "
        "Освободите небольшой промежуток без новых обязательств.",
        "В выборе станет яснее, какой вариант требует меньше лишних уступок. "
        "Сравните последствия на бумаге.",
        "В отношениях важным окажется не обещание, а последовательность. "
        "Отметьте, что повторяется в действиях.",
        "В обучении или поездке всплывёт полезный ориентир. "
        "Сохраните его и проверьте на практике.",
    )
    signs: list[dict[str, str]] = []
    for index, sign in enumerate(ZodiacSign):
        signs.append(
            {
                "sign": sign.value,
                "headline": f"Фокус дня {index + 1}",
                "central_idea": f"отдельная тема номер {index + 1}",
                "action": f"конкретный шаг номер {index + 1}",
                "text": texts[index],
            }
        )
    return {"theme": "День про точность перед следующим шагом", "signs": signs}


def _default_prompt_version(code: str) -> str:
    persona = persona_definition(code)
    assert persona is not None
    return persona.prompt_version


def test_new_personal_prompt_versions_are_defaults_and_legacy_still_loads() -> None:
    assert _default_prompt_version("tarot_reader") == "tarot-reader-v5"
    assert _default_prompt_version("love_oracle") == "love-oracle-v3"
    assert _default_prompt_version("mystical_psychologist") == "mystical-psychologist-v3"
    assert _default_prompt_version("astrologer") == "astrologer-v3"

    assert load_oracle_reading_prompts("tarot-reader-v4")
    assert load_oracle_reading_prompts("tarot-reader-v5")
    assert load_oracle_reading_prompts("love-oracle-v2")
    assert load_oracle_reading_prompts("love-oracle-v3")
    assert load_oracle_reading_prompts("mystical-psychologist-v2")
    assert load_oracle_reading_prompts("mystical-psychologist-v3")
    assert load_horoscope_prompts("astrologer-v2")
    assert load_horoscope_prompts("astrologer-v3")


def test_followup_v2_is_default_while_v1_remains_loadable() -> None:
    signature = inspect.signature(ReadingFollowUpService.__init__)
    assert signature.parameters["prompt_version"].default == "reading_followup_v2"
    assert load_reading_followup_prompts("reading_followup_v1").version == "reading_followup_v1"
    assert load_reading_followup_prompts("reading_followup_v2").version == "reading_followup_v2"


def test_memory_extraction_prompt_is_versioned() -> None:
    prompts = load_memory_extraction_prompts(MEMORY_EXTRACTION_PROMPT_VERSION)
    assert prompts.version == "oracle-memory-prompt-v1"
    assert "durable" in prompts.system


@pytest.mark.asyncio
async def test_daily_ai_builds_one_grounded_twelve_sign_snapshot() -> None:
    llm = FakeDailyLLM(_daily_payload())
    editor = DailyHoroscopeAIEditor(llm)
    base = build_daily_horoscope(date(2026, 10, 14))

    result = await editor.generate(base, {})

    assert result.snapshot.methodology_version == DAILY_AI_METHOD_VERSION
    assert len(result.snapshot.signs) == 12
    assert set(result.editorial_meta) == {sign.value for sign in ZodiacSign}
    assert llm.request is not None
    assert llm.request.telemetry_prompt_version == DAILY_HOROSCOPE_PROMPT_VERSION
    assert llm.request.telemetry_persona_code == "daily_horoscope"
    assert "DAILY_FACTS_JSON" in llm.request.user_prompt
    assert "RECENT_HISTORY_JSON" in llm.request.user_prompt


@pytest.mark.asyncio
async def test_daily_ai_rejects_recent_same_sign_editorial_repeat() -> None:
    payload = _daily_payload()
    llm = FakeDailyLLM(payload)
    editor = DailyHoroscopeAIEditor(llm)
    base = build_daily_horoscope(date(2026, 10, 14))
    raw_signs = cast(list[dict[str, str]], payload["signs"])
    first = raw_signs[0]
    history = {
        ZodiacSign.ARIES.value: [
            {
                "text": f"{first['headline']}. {first['text']}",
                "headline": first["headline"],
                "central_idea": first["central_idea"],
                "action": first["action"],
            }
        ]
    }

    with pytest.raises(InvalidDailyHoroscopeAIResultError):
        await editor.generate(base, history)


def test_temporal_daily_benchmark_detects_same_sign_repetition() -> None:
    items = [
        TemporalDailyItem(
            "2026-10-12", "Сверьте условия перед решением.", "Условия", "проверка", "сверьте"
        ),
        TemporalDailyItem(
            "2026-10-13", "Сверьте условия перед решением.", "Условия", "проверка", "сверьте"
        ),
        TemporalDailyItem(
            "2026-10-14", "Разговор даст новый ориентир.", "Разговор", "ясность", "спросите"
        ),
    ]
    report = evaluate_temporal_daily(items)
    assert report.sample_size == 3
    assert report.exact_duplicate_pairs == 1
    assert not report.passes_baseline


def test_routing_benchmark_measures_real_rules_without_changing_router() -> None:
    report = evaluate_routing()
    assert report.total >= 60
    assert set(report.expected_counts) == {
        "work",
        "love",
        "reflection",
        "decision",
        "general",
        "clarify",
    }
    assert 0.0 <= report.accuracy <= 1.0
    assert report.correct + len(report.mistakes) == report.total


def test_gold_examples_clear_offline_editorial_baseline() -> None:
    fixture = Path(__file__).parent / "fixtures" / "oracle_editorial_gold_examples.json"
    examples = json.loads(fixture.read_text(encoding="utf-8"))
    assert len(examples) >= 20
    for example in examples:
        report = evaluate_editorial_quality([example["text"]])
        assert report.passes_baseline, example
