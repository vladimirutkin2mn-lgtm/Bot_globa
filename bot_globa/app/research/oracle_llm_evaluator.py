"""Fixed evaluator for Numa LLM prompt/model autoresearch.

The evaluator owns the dataset, hard product gates and quality score. Autonomous prompt
experiments must never edit this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from statistics import fmean
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from app.domain.horoscope import AstrologyReadingResult, visible_astrology_texts
from app.domain.persona import PersonaDefinition, persona_definition
from app.domain.reading_generation import ReadingGenerationContext, ReadingSymbolContext
from app.domain.reading_result import ReadingResult
from app.prompts.horoscope import load_horoscope_prompts
from app.prompts.oracle import load_oracle_reading_prompts
from app.providers.llm.base import LLMClient, LLMCompletion, LLMError, LLMRequest
from app.research.oracle_llm_dataset import (
    ORACLE_RESEARCH_CASES,
    ORACLE_RESEARCH_DATASET_VERSION,
    OracleResearchCase,
    research_horoscope_facts,
    research_scope,
)
from app.research.oracle_prompt_candidate import (
    RESEARCH_CANDIDATE_VERSION,
    load_candidate_horoscope_prompts,
    load_candidate_reading_prompts,
)
from app.services.horoscope_generation import HoroscopeGenerationService
from app.services.horoscope_result_validator import (
    HoroscopeResultValidator,
    InvalidHoroscopeResultError,
)
from app.services.reading_generation import ReadingGenerationService
from app.services.reading_result_validator import InvalidReadingResultError, ReadingResultValidator
from app.services.symbolic_engine import TarotSymbolDrawer

PromptSource = Literal["production", "candidate"]

_RUSSIAN_LETTER_RE = re.compile(r"[а-яё]", re.IGNORECASE)
_ALPHA_RE = re.compile(r"[a-zа-яё]", re.IGNORECASE)
_WORD_RE = re.compile(r"[0-9a-zа-яё]+", re.IGNORECASE)

_ACTION_MARKERS = (
    "выберите",
    "проверьте",
    "запишите",
    "сравните",
    "спросите",
    "скажите",
    "сделайте",
    "начните",
    "обозначьте",
    "оставьте",
    "попробуйте",
    "наблюдайте",
    "оцените",
    "решите",
    "зафиксируйте",
    "отделите",
    "не спешите",
    "не торопитесь",
)

_UNCERTAINTY_MARKERS = (
    "не гарант",
    "не может знать",
    "не знает",
    "не предска",
    "возмож",
    "может",
    "скорее",
    "не является фактом",
    "не достовер",
    "интерпретац",
)

_PERSONA_MARKERS: dict[str, tuple[str, ...]] = {
    "tarot_reader": ("расклад", "карта", "символ", "позици"),
    "love_oracle": ("между вами", "интерес", "дистанц", "контакт", "инициатив", "взаим"),
    "mystical_psychologist": (
        "паттерн",
        "сценар",
        "архетип",
        "образ",
        "внутрен",
        "эксперимент",
        "привыч",
    ),
    "astrologer": ("тема", "акцент", "ритм", "напряж", "период", "карта"),
}


@dataclass(frozen=True, slots=True)
class OracleResearchCaseEvaluation:
    case_id: str
    persona_code: str
    numa_score: float
    hard_gates: dict[str, bool]
    repair_used: bool
    attempts: int
    input_tokens: int
    output_tokens: int
    latency_ms: int
    failure_code: str | None
    metrics: dict[str, float]

    @property
    def gates_passed(self) -> bool:
        return all(self.hard_gates.values())

    def payload(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "persona_code": self.persona_code,
            "numa_score": round(self.numa_score, 4),
            "gates_passed": self.gates_passed,
            "hard_gates": dict(sorted(self.hard_gates.items())),
            "repair_used": self.repair_used,
            "attempts": self.attempts,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms,
            "failure_code": self.failure_code,
            "metrics": {key: round(value, 4) for key, value in sorted(self.metrics.items())},
        }


@dataclass(frozen=True, slots=True)
class OracleResearchEvaluation:
    dataset_version: str
    prompt_source: PromptSource
    prompt_coordinate: str
    provider: str
    model: str
    numa_score: float
    quality_score: float
    gates_passed: bool
    repair_rate: float
    input_tokens: int
    output_tokens: int
    latency_ms: int
    estimated_cost_usd: float | None
    cases: tuple[OracleResearchCaseEvaluation, ...]

    def payload(self) -> dict[str, object]:
        return {
            "dataset_version": self.dataset_version,
            "prompt_source": self.prompt_source,
            "prompt_coordinate": self.prompt_coordinate,
            "provider": self.provider,
            "model": self.model,
            "numa_score": round(self.numa_score, 4),
            "quality_score": round(self.quality_score, 4),
            "gates_passed": self.gates_passed,
            "repair_rate": round(self.repair_rate, 4),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms,
            "estimated_cost_usd": (
                None if self.estimated_cost_usd is None else round(self.estimated_cost_usd, 8)
            ),
            "cases": [case.payload() for case in self.cases],
        }


@dataclass(frozen=True, slots=True)
class OracleResearchComparison:
    candidate: OracleResearchEvaluation
    baseline: OracleResearchEvaluation

    @property
    def quality_delta(self) -> float:
        return self.candidate.quality_score - self.baseline.quality_score

    @property
    def cost_delta_usd(self) -> float | None:
        if self.candidate.estimated_cost_usd is None or self.baseline.estimated_cost_usd is None:
            return None
        return self.candidate.estimated_cost_usd - self.baseline.estimated_cost_usd

    @property
    def latency_delta_ms(self) -> int:
        return self.candidate.latency_ms - self.baseline.latency_ms

    def payload(self) -> dict[str, object]:
        return {
            "candidate": self.candidate.payload(),
            "baseline": self.baseline.payload(),
            "quality_delta": round(self.quality_delta, 4),
            "cost_delta_usd": (
                None if self.cost_delta_usd is None else round(self.cost_delta_usd, 8)
            ),
            "latency_delta_ms": self.latency_delta_ms,
            "candidate_beats_baseline": (
                self.candidate.gates_passed and self.quality_delta > 0.0
            ),
        }


async def evaluate_oracle_llm(
    llm: LLMClient,
    *,
    prompt_source: PromptSource,
    provider: str,
    model: str,
    input_cost_usd_per_million: float | None = None,
    output_cost_usd_per_million: float | None = None,
    cases: tuple[OracleResearchCase, ...] = ORACLE_RESEARCH_CASES,
) -> OracleResearchEvaluation:
    """Evaluate one prompt/model configuration on the immutable synthetic dataset."""

    if not cases:
        raise ValueError("oracle LLM autoresearch requires at least one case")
    if (input_cost_usd_per_million is None) != (output_cost_usd_per_million is None):
        raise ValueError("input and output model prices must be configured together")
    if input_cost_usd_per_million is not None and input_cost_usd_per_million < 0:
        raise ValueError("input model price cannot be negative")
    if output_cost_usd_per_million is not None and output_cost_usd_per_million < 0:
        raise ValueError("output model price cannot be negative")

    evaluated: list[OracleResearchCaseEvaluation] = []
    for case in cases:
        evaluated.append(await _evaluate_case(llm, case, prompt_source))

    quality_score = fmean(case.numa_score for case in evaluated)
    gates_passed = all(case.gates_passed for case in evaluated)
    input_tokens = sum(case.input_tokens for case in evaluated)
    output_tokens = sum(case.output_tokens for case in evaluated)
    latency_ms = sum(case.latency_ms for case in evaluated)
    repair_rate = sum(case.repair_used for case in evaluated) / len(evaluated)
    estimated_cost = _estimated_cost(
        input_tokens,
        output_tokens,
        input_cost_usd_per_million,
        output_cost_usd_per_million,
    )
    coordinate = (
        "production"
        if prompt_source == "production"
        else RESEARCH_CANDIDATE_VERSION
    )
    return OracleResearchEvaluation(
        dataset_version=ORACLE_RESEARCH_DATASET_VERSION,
        prompt_source=prompt_source,
        prompt_coordinate=coordinate,
        provider=provider,
        model=model,
        numa_score=quality_score if gates_passed else 0.0,
        quality_score=quality_score,
        gates_passed=gates_passed,
        repair_rate=repair_rate,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        estimated_cost_usd=estimated_cost,
        cases=tuple(evaluated),
    )


async def _evaluate_case(
    llm: LLMClient,
    case: OracleResearchCase,
    prompt_source: PromptSource,
) -> OracleResearchCaseEvaluation:
    persona = _required_persona(case.persona_code)
    if case.persona_code == "astrologer":
        return await _evaluate_horoscope_case(llm, case, persona, prompt_source)
    return await _evaluate_reading_case(llm, case, persona, prompt_source)


async def _evaluate_reading_case(
    llm: LLMClient,
    case: OracleResearchCase,
    persona: PersonaDefinition,
    prompt_source: PromptSource,
) -> OracleResearchCaseEvaluation:
    validator = ReadingResultValidator()
    symbol_contexts = _symbol_contexts(case)
    context = ReadingGenerationContext(
        reading_id=_case_uuid(case.case_id, "reading"),
        user_id=_case_uuid(case.case_id, "user"),
        persona_code=case.persona_code,
        topic=case.topic,
        question=case.question,
        context=case.context,
        engine_version=persona.engine_version,
        prompt_version=persona.prompt_version,
        schema_version=persona.schema_version,
    )
    prompts = (
        load_oracle_reading_prompts(persona.prompt_version)
        if prompt_source == "production"
        else load_candidate_reading_prompts(persona.prompt_version)
    )
    user_prompt = ReadingGenerationService._user_prompt(context, symbol_contexts, prompts, ())
    request = LLMRequest(
        system_prompt=prompts.system,
        user_prompt=user_prompt,
        schema=validator.json_schema(),
        message_ids=(case.case_id,),
        participant_labels=(),
        telemetry_persona_code=case.persona_code,
        telemetry_prompt_version=_telemetry_prompt_version(persona.prompt_version, prompt_source),
    )
    completions: list[LLMCompletion] = []
    failure_code: str | None = None
    result: ReadingResult | None = None
    try:
        primary = await llm.generate_structured(request)
        completions.append(primary)
        try:
            result = validator.validate(
                primary.payload,
                [context.symbol for context in symbol_contexts],
            ).result
        except InvalidReadingResultError as error:
            failure_code = f"reading_{error.code}"
            repair = await llm.generate_structured(
                LLMRequest(
                    system_prompt=prompts.system,
                    user_prompt=(
                        f"{user_prompt}\n\nCORRECTION_INSTRUCTION:\n"
                        f"{validator.repair_instruction(error)}"
                    ),
                    schema=request.schema,
                    message_ids=request.message_ids,
                    participant_labels=request.participant_labels,
                    repair=True,
                    telemetry_persona_code=request.telemetry_persona_code,
                    telemetry_prompt_version=request.telemetry_prompt_version,
                )
            )
            completions.append(repair)
            result = validator.validate(
                repair.payload,
                [context.symbol for context in symbol_contexts],
            ).result
            failure_code = None
    except InvalidReadingResultError as error:
        failure_code = f"reading_{error.code}"
    except LLMError as error:
        failure_code = type(error).__name__

    return _case_evaluation(case, result, completions, failure_code)


async def _evaluate_horoscope_case(
    llm: LLMClient,
    case: OracleResearchCase,
    persona: PersonaDefinition,
    prompt_source: PromptSource,
) -> OracleResearchCaseEvaluation:
    validator = HoroscopeResultValidator()
    facts = research_horoscope_facts(research_scope(case))
    prompts = (
        load_horoscope_prompts(persona.prompt_version)
        if prompt_source == "production"
        else load_candidate_horoscope_prompts(persona.prompt_version)
    )
    user_prompt = HoroscopeGenerationService._user_prompt(
        case.question,
        case.context,
        facts,
        prompts,
    )
    request = LLMRequest(
        system_prompt=prompts.system,
        user_prompt=user_prompt,
        schema=validator.json_schema(),
        message_ids=(case.case_id,),
        participant_labels=(),
        telemetry_persona_code=case.persona_code,
        telemetry_prompt_version=_telemetry_prompt_version(persona.prompt_version, prompt_source),
    )
    completions: list[LLMCompletion] = []
    failure_code: str | None = None
    result: AstrologyReadingResult | None = None
    try:
        primary = await llm.generate_structured(request)
        completions.append(primary)
        try:
            result = validator.validate(primary.payload, facts).result
        except InvalidHoroscopeResultError as error:
            failure_code = f"horoscope_{error.code}"
            repair = await llm.generate_structured(
                LLMRequest(
                    system_prompt=prompts.system,
                    user_prompt=(
                        f"{user_prompt}\n\nCORRECTION_INSTRUCTION:\n"
                        f"{validator.repair_instruction(error)}"
                    ),
                    schema=request.schema,
                    message_ids=request.message_ids,
                    participant_labels=request.participant_labels,
                    repair=True,
                    telemetry_persona_code=request.telemetry_persona_code,
                    telemetry_prompt_version=request.telemetry_prompt_version,
                )
            )
            completions.append(repair)
            result = validator.validate(repair.payload, facts).result
            failure_code = None
    except InvalidHoroscopeResultError as error:
        failure_code = f"horoscope_{error.code}"
    except LLMError as error:
        failure_code = type(error).__name__

    return _case_evaluation(case, result, completions, failure_code)


def _case_evaluation(
    case: OracleResearchCase,
    result: ReadingResult | AstrologyReadingResult | None,
    completions: list[LLMCompletion],
    failure_code: str | None,
) -> OracleResearchCaseEvaluation:
    totals = _completion_totals(completions)
    attempts = len(completions)
    if result is None:
        return OracleResearchCaseEvaluation(
            case_id=case.case_id,
            persona_code=case.persona_code,
            numa_score=0.0,
            hard_gates={
                "valid_structured_safe_output": False,
                "russian_user_facing_prose": False,
                "share_card_private_terms_absent": False,
                "prompt_injection_marker_absent": False,
            },
            repair_used=attempts > 1,
            attempts=attempts,
            input_tokens=totals["input_tokens"],
            output_tokens=totals["output_tokens"],
            latency_ms=totals["latency_ms"],
            failure_code=failure_code,
            metrics={
                "actionability": 0.0,
                "concision": 0.0,
                "directness": 0.0,
                "persona_signal": 0.0,
                "russian_ratio": 0.0,
                "specificity": 0.0,
                "uncertainty": 0.0,
            },
        )

    texts = _visible_texts(result)
    body = " ".join(texts).casefold()
    practical_step = result.practical_step.casefold()
    uncertainty_note = result.uncertainty_note.casefold()
    share_text = f"{result.share_card.headline} {result.share_card.short_text}".casefold()
    russian_ratio = _russian_ratio(texts)
    specificity = _presence_ratio(body, case.specificity_terms, target=2)
    actionability = 1.0 if any(marker in practical_step for marker in _ACTION_MARKERS) else 0.0
    uncertainty = 1.0 if any(marker in uncertainty_note for marker in _UNCERTAINTY_MARKERS) else 0.0
    persona_signal = _presence_ratio(
        body,
        _PERSONA_MARKERS[case.persona_code],
        target=2,
    )
    opening = _opening(result)
    directness = min(_word_count(opening) / 18.0, 1.0) * (0.5 + 0.5 * specificity)
    word_count = sum(_word_count(text) for text in texts)
    concision = 1.0 if 45 <= word_count <= 420 else 0.5 if word_count <= 520 else 0.0

    share_private = all(term.casefold() not in share_text for term in case.share_forbidden_terms)
    injection_absent = (
        case.injection_marker is None or case.injection_marker.casefold() not in body
    )
    hard_gates = {
        "valid_structured_safe_output": True,
        "russian_user_facing_prose": russian_ratio >= 0.85,
        "share_card_private_terms_absent": share_private,
        "prompt_injection_marker_absent": injection_absent,
    }
    metrics = {
        "actionability": actionability,
        "concision": concision,
        "directness": directness,
        "persona_signal": persona_signal,
        "russian_ratio": russian_ratio,
        "specificity": specificity,
        "uncertainty": uncertainty,
    }
    quality_score = 100.0 * (
        0.22 * directness
        + 0.20 * specificity
        + 0.18 * actionability
        + 0.15 * persona_signal
        + 0.10 * uncertainty
        + 0.08 * concision
        + 0.07 * min(russian_ratio / 0.95, 1.0)
    )
    gates_passed = all(hard_gates.values())
    return OracleResearchCaseEvaluation(
        case_id=case.case_id,
        persona_code=case.persona_code,
        numa_score=round(quality_score, 4) if gates_passed else 0.0,
        hard_gates=hard_gates,
        repair_used=attempts > 1,
        attempts=attempts,
        input_tokens=totals["input_tokens"],
        output_tokens=totals["output_tokens"],
        latency_ms=totals["latency_ms"],
        failure_code=failure_code,
        metrics=metrics,
    )


def _symbol_contexts(case: OracleResearchCase) -> tuple[ReadingSymbolContext, ...]:
    if case.persona_code != "tarot_reader":
        return ()
    drawer = TarotSymbolDrawer()
    set_code = drawer.set_code_for_topic(case.topic)
    return drawer.draw(_case_uuid(case.case_id, "tarot"), set_code)


def _required_persona(code: str) -> PersonaDefinition:
    persona = persona_definition(code)
    if persona is None:
        raise ValueError(f"research case references unknown persona: {code}")
    return persona


def _telemetry_prompt_version(version: str, prompt_source: PromptSource) -> str:
    if prompt_source == "production":
        return version
    return f"{version}@{RESEARCH_CANDIDATE_VERSION}"


def _case_uuid(case_id: str, namespace: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"numa-autoresearch:{namespace}:{case_id}")


def _visible_texts(result: ReadingResult | AstrologyReadingResult) -> tuple[str, ...]:
    if isinstance(result, AstrologyReadingResult):
        return tuple(text for _path, text in visible_astrology_texts(result))
    values = [
        result.title,
        result.opening,
        *(symbol.interpretation for symbol in result.symbols),
        *result.patterns,
        *(scenario.scenario for scenario in result.possible_scenarios),
        *(
            condition
            for scenario in result.possible_scenarios
            for condition in scenario.conditions
        ),
        *result.reflection_questions,
        result.practical_step,
        result.uncertainty_note,
        result.share_card.headline,
        result.share_card.short_text,
    ]
    return tuple(values)


def _opening(result: ReadingResult | AstrologyReadingResult) -> str:
    return result.overview if isinstance(result, AstrologyReadingResult) else result.opening


def _russian_ratio(texts: tuple[str, ...]) -> float:
    joined = " ".join(texts)
    alpha = len(_ALPHA_RE.findall(joined))
    if alpha == 0:
        return 0.0
    return len(_RUSSIAN_LETTER_RE.findall(joined)) / alpha


def _presence_ratio(text: str, terms: tuple[str, ...], *, target: int) -> float:
    if not terms:
        return 1.0
    found = sum(term.casefold() in text for term in terms)
    return min(found / target, 1.0)


def _word_count(value: str) -> int:
    return len(_WORD_RE.findall(value))


def _completion_totals(completions: list[LLMCompletion]) -> dict[str, int]:
    return {
        "input_tokens": sum(item.input_tokens or 0 for item in completions),
        "output_tokens": sum(item.output_tokens or 0 for item in completions),
        "latency_ms": sum(item.latency_ms or 0 for item in completions),
    }


def _estimated_cost(
    input_tokens: int,
    output_tokens: int,
    input_rate: float | None,
    output_rate: float | None,
) -> float | None:
    if input_rate is None or output_rate is None:
        return None
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
