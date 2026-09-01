"""Deterministic coverage for the Numa LLM autoresearch harness."""

import json
from collections import Counter

from app.prompts.horoscope import load_horoscope_prompts
from app.prompts.oracle import load_oracle_reading_prompts
from app.providers.llm.base import LLMCompletion, LLMRequest
from app.research.oracle_llm_dataset import ORACLE_RESEARCH_CASES
from app.research.oracle_llm_evaluator import evaluate_oracle_llm
from app.research.oracle_prompt_candidate import (
    load_candidate_horoscope_prompts,
    load_candidate_reading_prompts,
)


class GoldenResearchLLM:
    def __init__(self, *, invalid_first: bool = False) -> None:
        self.invalid_first = invalid_first
        self.calls = 0

    async def generate_structured(self, request: LLMRequest) -> LLMCompletion:
        self.calls += 1
        if self.invalid_first and self.calls == 1:
            return LLMCompletion(
                payload="{not-json",
                provider="research-fake",
                model="golden",
                input_tokens=100,
                output_tokens=50,
                latency_ms=10,
            )
        payload = (
            _horoscope_payload(request)
            if request.telemetry_persona_code == "astrologer"
            else _reading_payload(request)
        )
        return LLMCompletion(
            payload=json.dumps(payload, ensure_ascii=False),
            provider="research-fake",
            model="golden",
            input_tokens=100,
            output_tokens=50,
            latency_ms=10,
        )


def _reading_payload(request: LLMRequest) -> dict[str, object]:
    raw = request.user_prompt.split("INPUT_JSON:\n", 1)[1]
    input_payload = json.loads(raw)
    persona = request.telemetry_persona_code
    selected = input_payload["selected_symbols"]

    if persona == "love_oracle":
        opening = (
            "Между вами сейчас скорее заметна дистанция, поэтому лучше смотреть на "
            "конкретные сигналы и взаимность действий."
        )
        pattern = "Контакт и инициатива сейчас важнее догадок о чувствах другого человека."
    elif persona == "mystical_psychologist":
        opening = (
            "Здесь заметен повторяющийся внутренний сценарий: напряжение усиливается "
            "ровно перед моментом выбора."
        )
        pattern = "Этот паттерн можно проверить небольшим экспериментом вместо нового анализа."
    else:
        opening = (
            "Расклад показывает напряжение между импульсом действовать и необходимостью "
            "сначала проверить ситуацию."
        )
        pattern = "Карты в раскладе связывают паузу, выбор и следующий небольшой шаг."

    symbols = [
        {
            "symbol_id": item["symbol_id"],
            "position": item["position"],
            "orientation": item["orientation"],
            "interpretation": (
                "Эта позиция символически подчёркивает необходимость проверить наблюдаемые факты."
            ),
        }
        for item in selected
    ]
    return {
        "title": "Ясный ориентир для текущей ситуации",
        "opening": opening,
        "symbols": symbols,
        "patterns": [pattern],
        "possible_scenarios": [
            {
                "scenario": "Ситуация станет понятнее после одного небольшого проверяемого шага.",
                "conditions": ["Сначала отделите наблюдаемый факт от предположения."],
            }
        ],
        "reflection_questions": [
            "Какой факт изменил бы ваше решение, если бы вы узнали его сегодня?"
        ],
        "practical_step": "Запишите один факт и выберите один небольшой обратимый шаг.",
        "uncertainty_note": (
            "Это интерпретация возможного сценария, а не достоверное знание о будущем."
        ),
        "share_card": {
            "headline": "Ясность начинается с наблюдаемого",
            "short_text": "Один небольшой шаг может дать больше информации, чем догадки.",
        },
        "safety": {"high_risk_detected": False, "categories": []},
    }


def _horoscope_payload(request: LLMRequest) -> dict[str, object]:
    input_block, facts_block = request.user_prompt.split("\n\nFACT_BUNDLE_JSON:\n", 1)
    input_payload = json.loads(input_block.split("INPUT_JSON:\n", 1)[1])
    facts = json.loads(facts_block)
    fact_id = facts["facts"][0]["fact_id"]
    return {
        "title": "Главный акцент вашей карты",
        "scope": input_payload["scope"],
        "facts_digest": input_payload["facts_digest"],
        "overview": (
            "Сейчас в теме решения заметен акцент на устойчивом ритме и проверке импульса "
            "перед важным шагом."
        ),
        "interpretations": [
            {
                "fact_ids": [fact_id],
                "text": (
                    "Этот рассчитанный фактор можно интерпретировать как тему устойчивости "
                    "и внимательного выбора темпа."
                ),
            }
        ],
        "themes": ["Главная тема — соединить инициативу с устойчивым темпом."],
        "possible_scenarios": [
            {
                "scenario": "Решение станет яснее после небольшого обратимого эксперимента.",
                "conditions": ["Сначала проверьте один практический критерий выбора."],
            }
        ],
        "reflection_questions": ["Какой критерий сделает решение для вас устойчивее?"],
        "practical_step": "Запишите критерии и проверьте один вариант небольшим шагом.",
        "limitations": facts["limitations"],
        "uncertainty_note": (
            "Астрологическая интерпретация не предсказывает событие и не гарантирует результат."
        ),
        "share_card": {
            "headline": "Устойчивый ритм важнее спешки",
            "short_text": "Проверьте один критерий, прежде чем делать большой шаг.",
        },
        "safety": {"high_risk_detected": False, "categories": []},
    }


def test_fixed_dataset_covers_all_four_personas_evenly() -> None:
    counts = Counter(case.persona_code for case in ORACLE_RESEARCH_CASES)

    assert len(ORACLE_RESEARCH_CASES) == 12
    assert counts == {
        "tarot_reader": 3,
        "love_oracle": 3,
        "mystical_psychologist": 3,
        "astrologer": 3,
    }
    assert len({case.case_id for case in ORACLE_RESEARCH_CASES}) == len(ORACLE_RESEARCH_CASES)
    assert all(case.question.strip() for case in ORACLE_RESEARCH_CASES)


def test_candidate_starts_from_exact_production_prompt_baseline() -> None:
    for version in ("tarot-reader-v4", "love-oracle-v2", "mystical-psychologist-v2"):
        assert load_candidate_reading_prompts(version) == load_oracle_reading_prompts(version)
    assert load_candidate_horoscope_prompts("astrologer-v2") == load_horoscope_prompts(
        "astrologer-v2"
    )


async def test_golden_model_passes_product_gates_and_reports_cost() -> None:
    llm = GoldenResearchLLM()
    evaluation = await evaluate_oracle_llm(
        llm,
        prompt_source="candidate",
        provider="research-fake",
        model="golden",
        input_cost_usd_per_million=2.0,
        output_cost_usd_per_million=6.0,
    )

    assert evaluation.gates_passed
    assert evaluation.numa_score == evaluation.quality_score
    assert evaluation.numa_score > 0
    assert evaluation.repair_rate == 0
    assert evaluation.input_tokens == 1_200
    assert evaluation.output_tokens == 600
    assert evaluation.latency_ms == 120
    assert evaluation.estimated_cost_usd == 0.006
    assert all(case.failure_code is None for case in evaluation.cases)


async def test_invalid_primary_is_repaired_once_and_counted() -> None:
    llm = GoldenResearchLLM(invalid_first=True)
    evaluation = await evaluate_oracle_llm(
        llm,
        prompt_source="production",
        provider="research-fake",
        model="golden",
        cases=(ORACLE_RESEARCH_CASES[0],),
    )

    assert evaluation.gates_passed
    assert evaluation.repair_rate == 1.0
    assert evaluation.cases[0].repair_used
    assert evaluation.cases[0].attempts == 2
    assert evaluation.cases[0].failure_code is None
