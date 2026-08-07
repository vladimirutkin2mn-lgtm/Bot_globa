"""Generate, validate and persist Horoscope readings bound to calculated facts."""

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from app.domain.horoscope import (
    AstrologyReadingResult,
    HoroscopeFactBundle,
    HoroscopeLimitation,
    HoroscopeScope,
)
from app.domain.horoscope_topic import HoroscopeTopic
from app.domain.reading import ReadingSymbolInput
from app.domain.reading_generation import (
    ReadingGenerationClaim,
    ReadingGenerationClaimStatus,
    ReadingGenerationFinalizeStatus,
)
from app.prompts.horoscope import (
    HoroscopePromptNotFoundError,
    HoroscopePromptSet,
    load_horoscope_prompts,
)
from app.providers.analytics import OracleProductEvent
from app.providers.llm.base import (
    LLMAuthenticationError,
    LLMClient,
    LLMCompletion,
    LLMInvalidRequestError,
    LLMRateLimitError,
    LLMRequest,
    LLMTimeoutError,
    LLMTransientError,
    LLMUnexpectedError,
)
from app.services.horoscope_result_validator import (
    HoroscopeResultValidator,
    InvalidHoroscopeResult,
)
from app.services.horoscope_storage import (
    InvalidStoredHoroscope,
    deserialize_horoscope,
    serialize_horoscope,
)
from app.services.natal_chart import BirthProfileUnavailableError
from app.services.oracle_product_analytics import (
    OracleAnalyticsValue,
    OracleProductAnalytics,
)

logger = logging.getLogger(__name__)


class HoroscopeGenerationStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    ALREADY_PROCESSING = "already_processing"
    NOT_READY = "not_ready"
    PERSONA_DISABLED = "persona_disabled"
    DELETED = "deleted"
    NOT_FOUND = "not_found"
    CORRUPTED_RESULT = "corrupted_result"


@dataclass(frozen=True, slots=True)
class HoroscopeGenerationResult:
    status: HoroscopeGenerationStatus
    result: AstrologyReadingResult | None = None
    facts: HoroscopeFactBundle | None = None
    failure_code: str | None = None
    attempt_count: int = 0
    repair_used: bool = False
    idempotent: bool = False
    provider: str | None = None
    model: str | None = None


class HoroscopeGenerationStore(Protocol):
    async def claim_preview(self, reading_id: UUID, user_id: UUID) -> ReadingGenerationClaim: ...

    async def complete_preview(
        self,
        reading_id: UUID,
        user_id: UUID,
        result: dict[str, object],
        symbols: tuple[ReadingSymbolInput, ...],
    ) -> ReadingGenerationFinalizeStatus: ...

    async def fail_generation(
        self,
        reading_id: UUID,
        user_id: UUID,
        failure_code: str,
    ) -> ReadingGenerationFinalizeStatus: ...


class HoroscopeFactsProvider(Protocol):
    async def calculate_for_user(
        self,
        user_id: UUID,
        scope: HoroscopeScope,
        *,
        reference_date: date | None = None,
    ) -> HoroscopeFactBundle: ...


class HoroscopeGenerationService:
    """Provider-neutral Horoscope generation with one optional payload-free repair."""

    def __init__(
        self,
        store: HoroscopeGenerationStore,
        llm: LLMClient,
        facts: HoroscopeFactsProvider,
        *,
        max_repair_attempts: int = 1,
        prompt_loader: Callable[[str], HoroscopePromptSet] = load_horoscope_prompts,
        validator: HoroscopeResultValidator | None = None,
        analytics: OracleProductAnalytics | None = None,
    ) -> None:
        if max_repair_attempts not in {0, 1}:
            raise ValueError("Horoscope generation allows at most one repair attempt")
        self._store = store
        self._llm = llm
        self._facts = facts
        self._max_repairs = max_repair_attempts
        self._prompt_loader = prompt_loader
        self._validator = validator or HoroscopeResultValidator()
        self._analytics = analytics

    async def generate_preview(
        self,
        reading_id: UUID,
        user_id: UUID,
    ) -> HoroscopeGenerationResult:
        claim = await self._store.claim_preview(reading_id, user_id)
        if claim.status is ReadingGenerationClaimStatus.READY:
            return self._ready_result(claim)
        mapped = self._map_claim(claim.status)
        if mapped is not None:
            return HoroscopeGenerationResult(mapped)
        if claim.context is None:
            return HoroscopeGenerationResult(
                HoroscopeGenerationStatus.FAILED,
                failure_code="invalid_generation_claim",
            )
        context = claim.context
        attempts = 0
        completion: LLMCompletion | None = None
        try:
            if context.persona_code != "astrologer":
                return await self._fail(
                    reading_id,
                    user_id,
                    "persona_mismatch",
                    attempts,
                    completion,
                )
            if context.engine_version != "astrology-calculation-v1":
                return await self._fail(
                    reading_id,
                    user_id,
                    "engine_version_mismatch",
                    attempts,
                    completion,
                )
            if context.schema_version != self._validator.schema_version:
                return await self._fail(
                    reading_id,
                    user_id,
                    "schema_version_mismatch",
                    attempts,
                    completion,
                )
            topic = HoroscopeTopic.parse(context.topic)
            scope = topic.scope
            prompts = self._prompt_loader(context.prompt_version)
            facts = await self._facts.calculate_for_user(
                user_id,
                scope,
                reference_date=topic.reference_date,
            )
            user_prompt = self._user_prompt(context.question, context.context, facts, prompts)
            request = LLMRequest(
                system_prompt=prompts.system,
                user_prompt=user_prompt,
                schema=self._validator.json_schema(),
                message_ids=(str(reading_id),),
                participant_labels=(),
            )
            attempts += 1
            completion = await self._llm.generate_analysis(request)
            try:
                validated = self._validator.validate(completion.payload, facts)
            except InvalidHoroscopeResult as error:
                if self._max_repairs == 0:
                    raise
                attempts += 1
                completion = await self._llm.generate_analysis(
                    LLMRequest(
                        system_prompt=prompts.system,
                        user_prompt=(
                            f"{user_prompt}\n\nCORRECTION_INSTRUCTION:\n"
                            f"{self._validator.repair_instruction(error)}"
                        ),
                        schema=request.schema,
                        message_ids=request.message_ids,
                        participant_labels=request.participant_labels,
                        repair=True,
                    )
                )
                validated = self._validator.validate(completion.payload, facts)
            finalized = await self._store.complete_preview(
                reading_id,
                user_id,
                serialize_horoscope(validated.result, facts),
                (),
            )
            if finalized is not ReadingGenerationFinalizeStatus.COMPLETED:
                return self._finalize_conflict(finalized, attempts, completion)
            logger.info(
                "horoscope_generation_completed reading_id=%s provider=%s model=%s "
                "prompt_version=%s facts_version=%s fact_count=%s attempt=%s",
                reading_id,
                completion.provider,
                completion.model,
                context.prompt_version,
                facts.facts_version,
                len(facts.facts),
                attempts,
            )
            time_precision = (
                "date_only"
                if HoroscopeLimitation.BIRTH_TIME_UNKNOWN in facts.limitations
                else "exact"
            )
            await self._track(
                user_id,
                OracleProductEvent.ASTROLOGY_CALCULATION_COMPLETED,
                {
                    "scope_code": facts.scope,
                    "chart_schema_version": facts.natal_schema_version,
                    "engine_version": facts.natal_engine_version,
                    "time_precision": time_precision,
                    "house_system": "equal-house-v1" if time_precision == "exact" else None,
                },
            )
            await self._track(
                user_id,
                OracleProductEvent.READING_PREVIEW_READY,
                {
                    "reading_id": reading_id,
                    "persona_code": context.persona_code,
                    "topic_code": context.topic,
                    "engine_version": context.engine_version,
                    "prompt_version": context.prompt_version,
                    "schema_version": context.schema_version,
                    "attempt_count": attempts,
                    "repair_used": attempts > 1,
                    "memory_count": 0,
                },
            )
            return HoroscopeGenerationResult(
                HoroscopeGenerationStatus.COMPLETED,
                result=validated.result,
                facts=facts,
                attempt_count=attempts,
                repair_used=attempts > 1,
                provider=completion.provider,
                model=completion.model,
            )
        except asyncio.CancelledError:
            try:
                await self._store.fail_generation(
                    reading_id,
                    user_id,
                    "generation_cancelled",
                )
            finally:
                raise
        except HoroscopePromptNotFoundError:
            return await self._fail(
                reading_id,
                user_id,
                "prompt_not_found",
                attempts,
                completion,
            )
        except BirthProfileUnavailableError:
            return await self._fail(
                reading_id,
                user_id,
                "birth_profile_unavailable",
                attempts,
                completion,
            )
        except InvalidHoroscopeResult as error:
            return await self._fail(
                reading_id,
                user_id,
                f"horoscope_{error.code}",
                attempts,
                completion,
            )
        except LLMTimeoutError:
            return await self._fail(reading_id, user_id, "llm_timeout", attempts, completion)
        except LLMRateLimitError:
            return await self._fail(
                reading_id,
                user_id,
                "llm_rate_limited",
                attempts,
                completion,
            )
        except LLMAuthenticationError:
            return await self._fail(
                reading_id,
                user_id,
                "llm_authentication_error",
                attempts,
                completion,
            )
        except LLMInvalidRequestError:
            return await self._fail(
                reading_id,
                user_id,
                "llm_invalid_request",
                attempts,
                completion,
            )
        except LLMTransientError:
            return await self._fail(
                reading_id,
                user_id,
                "llm_transient_error",
                attempts,
                completion,
            )
        except LLMUnexpectedError:
            return await self._fail(
                reading_id,
                user_id,
                "unexpected_provider_error",
                attempts,
                completion,
            )
        except (TypeError, ValueError):
            return await self._fail(
                reading_id,
                user_id,
                "invalid_generation_input",
                attempts,
                completion,
            )
        except Exception:
            return await self._fail(
                reading_id,
                user_id,
                "unexpected_pipeline_error",
                attempts,
                completion,
            )

    def _ready_result(self, claim: ReadingGenerationClaim) -> HoroscopeGenerationResult:
        if claim.ready is None or claim.ready.symbols:
            return HoroscopeGenerationResult(HoroscopeGenerationStatus.CORRUPTED_RESULT)
        try:
            stored_result, facts = deserialize_horoscope(claim.ready.payload)
            validated = self._validator.validate(
                json.dumps(stored_result.model_dump(mode="json"), ensure_ascii=False),
                facts,
            )
        except (InvalidStoredHoroscope, InvalidHoroscopeResult):
            return HoroscopeGenerationResult(HoroscopeGenerationStatus.CORRUPTED_RESULT)
        return HoroscopeGenerationResult(
            HoroscopeGenerationStatus.COMPLETED,
            result=validated.result,
            facts=facts,
            idempotent=True,
        )

    @staticmethod
    def _map_claim(
        status: ReadingGenerationClaimStatus,
    ) -> HoroscopeGenerationStatus | None:
        values = {
            ReadingGenerationClaimStatus.ALREADY_PROCESSING: (
                HoroscopeGenerationStatus.ALREADY_PROCESSING
            ),
            ReadingGenerationClaimStatus.NOT_READY: HoroscopeGenerationStatus.NOT_READY,
            ReadingGenerationClaimStatus.PERSONA_DISABLED: (
                HoroscopeGenerationStatus.PERSONA_DISABLED
            ),
            ReadingGenerationClaimStatus.DELETED: HoroscopeGenerationStatus.DELETED,
            ReadingGenerationClaimStatus.NOT_FOUND: HoroscopeGenerationStatus.NOT_FOUND,
            ReadingGenerationClaimStatus.CORRUPTED_RESULT: (
                HoroscopeGenerationStatus.CORRUPTED_RESULT
            ),
        }
        return values.get(status)

    @staticmethod
    def _user_prompt(
        question: str,
        context: str | None,
        facts: HoroscopeFactBundle,
        prompts: HoroscopePromptSet,
    ) -> str:
        input_payload = {
            "scope": facts.scope.value,
            "facts_digest": facts.digest(),
            "user_question": question,
            "optional_context": context,
        }
        return (
            f"{prompts.request_instruction}\n\nINPUT_JSON:\n"
            f"{json.dumps(input_payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
            "FACT_BUNDLE_JSON:\n"
            f"{json.dumps(facts.payload(), ensure_ascii=False, separators=(',', ':'))}"
        )

    async def _fail(
        self,
        reading_id: UUID,
        user_id: UUID,
        failure_code: str,
        attempts: int,
        completion: LLMCompletion | None,
    ) -> HoroscopeGenerationResult:
        finalized = await self._store.fail_generation(reading_id, user_id, failure_code)
        if finalized is ReadingGenerationFinalizeStatus.DELETED:
            return HoroscopeGenerationResult(HoroscopeGenerationStatus.DELETED)
        if finalized is ReadingGenerationFinalizeStatus.NOT_FOUND:
            return HoroscopeGenerationResult(HoroscopeGenerationStatus.NOT_FOUND)
        logger.warning(
            "horoscope_generation_failed reading_id=%s provider=%s model=%s "
            "attempt=%s failure_code=%s finalize_status=%s",
            reading_id,
            completion.provider if completion else "unknown",
            completion.model if completion else "unknown",
            attempts,
            failure_code,
            finalized.value,
        )
        return HoroscopeGenerationResult(
            HoroscopeGenerationStatus.FAILED,
            failure_code=failure_code,
            attempt_count=attempts,
            repair_used=attempts > 1,
            provider=completion.provider if completion else None,
            model=completion.model if completion else None,
        )

    @staticmethod
    def _finalize_conflict(
        status: ReadingGenerationFinalizeStatus,
        attempts: int,
        completion: LLMCompletion,
    ) -> HoroscopeGenerationResult:
        mapped = {
            ReadingGenerationFinalizeStatus.DELETED: HoroscopeGenerationStatus.DELETED,
            ReadingGenerationFinalizeStatus.NOT_FOUND: HoroscopeGenerationStatus.NOT_FOUND,
        }.get(status, HoroscopeGenerationStatus.FAILED)
        return HoroscopeGenerationResult(
            mapped,
            failure_code=(
                "generation_state_conflict"
                if status is ReadingGenerationFinalizeStatus.STATE_CONFLICT
                else None
            ),
            attempt_count=attempts,
            repair_used=attempts > 1,
            provider=completion.provider,
            model=completion.model,
        )

    async def _track(
        self,
        user_id: UUID,
        event: OracleProductEvent,
        properties: dict[str, OracleAnalyticsValue | None],
    ) -> None:
        if self._analytics is None:
            return
        try:
            await self._analytics.track(user_id, event, properties)
        except Exception:
            logger.warning("oracle_analytics_failed event=%s", event.value)
