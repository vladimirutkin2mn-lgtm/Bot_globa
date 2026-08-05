"""Generate, validate, repair once, and persist structured oracle readings."""

import asyncio
import json
import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from app.domain.reading import ReadingSymbolInput
from app.domain.reading_generation import (
    ReadingGenerationClaim,
    ReadingGenerationClaimStatus,
    ReadingGenerationFinalizeStatus,
    ReadingSymbolContext,
)
from app.domain.reading_result import ReadingResult
from app.prompts.reading import (
    ReadingPromptNotFoundError,
    ReadingPromptSet,
    load_reading_prompts,
)
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
from app.services.reading_result_validator import InvalidReadingResult, ReadingResultValidator

logger = logging.getLogger(__name__)


class ReadingGenerationStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    ALREADY_PROCESSING = "already_processing"
    NOT_READY = "not_ready"
    PERSONA_DISABLED = "persona_disabled"
    DELETED = "deleted"
    NOT_FOUND = "not_found"
    CORRUPTED_RESULT = "corrupted_result"


@dataclass(frozen=True, slots=True)
class ReadingGenerationResult:
    status: ReadingGenerationStatus
    result: ReadingResult | None = None
    failure_code: str | None = None
    attempt_count: int = 0
    repair_used: bool = False
    idempotent: bool = False
    provider: str | None = None
    model: str | None = None


class ReadingGenerationStore(Protocol):
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


class ReadingGenerationService:
    """Provider-neutral generation with at most one payload-free repair attempt."""

    def __init__(
        self,
        store: ReadingGenerationStore,
        llm: LLMClient,
        *,
        max_repair_attempts: int = 1,
        prompt_loader: type[object] | None = None,
        validator: ReadingResultValidator | None = None,
    ) -> None:
        if max_repair_attempts not in {0, 1}:
            raise ValueError("reading generation allows at most one repair attempt")
        self._store = store
        self._llm = llm
        self._max_repairs = max_repair_attempts
        self._prompt_loader = load_reading_prompts if prompt_loader is None else prompt_loader
        self._validator = validator or ReadingResultValidator()

    async def generate_preview(
        self,
        reading_id: UUID,
        user_id: UUID,
        symbol_contexts: tuple[ReadingSymbolContext, ...],
    ) -> ReadingGenerationResult:
        claim = await self._store.claim_preview(reading_id, user_id)
        if claim.status is ReadingGenerationClaimStatus.READY:
            return self._ready_result(claim)
        mapped = self._map_claim(claim.status)
        if mapped is not None:
            return ReadingGenerationResult(mapped)
        if claim.context is None:
            return ReadingGenerationResult(
                ReadingGenerationStatus.FAILED,
                failure_code="invalid_generation_claim",
            )
        context = claim.context
        attempts = 0
        last_completion: LLMCompletion | None = None
        try:
            expected_symbols = self._expected_symbols(symbol_contexts)
            if context.schema_version != self._validator.schema_version:
                return await self._fail(
                    reading_id,
                    user_id,
                    "schema_version_mismatch",
                    attempts,
                    last_completion,
                )
            prompts = self._load_prompts(context.prompt_version)
            user_prompt = self._user_prompt(context, symbol_contexts, prompts)
            request = LLMRequest(
                system_prompt=prompts.system,
                user_prompt=user_prompt,
                schema=self._validator.json_schema(),
                message_ids=(str(reading_id),),
                participant_labels=(),
            )
            attempts += 1
            last_completion = await self._llm.generate_analysis(request)
            try:
                validated = self._validator.validate(last_completion.payload, list(expected_symbols))
            except InvalidReadingResult as error:
                if self._max_repairs == 0:
                    raise
                repair_prompt = (
                    f"{user_prompt}\n\nCORRECTION_INSTRUCTION:\n"
                    f"{self._validator.repair_instruction(error)}"
                )
                attempts += 1
                last_completion = await self._llm.generate_analysis(
                    LLMRequest(
                        system_prompt=prompts.system,
                        user_prompt=repair_prompt,
                        schema=request.schema,
                        message_ids=request.message_ids,
                        participant_labels=request.participant_labels,
                        repair=True,
                    )
                )
                validated = self._validator.validate(
                    last_completion.payload,
                    list(expected_symbols),
                )
            finalized = await self._store.complete_preview(
                reading_id,
                user_id,
                validated.result.model_dump(mode="json"),
                expected_symbols,
            )
            if finalized is not ReadingGenerationFinalizeStatus.COMPLETED:
                return self._finalize_conflict(finalized, attempts, last_completion)
            logger.info(
                "reading_generation_completed reading_id=%s provider=%s model=%s "
                "prompt_version=%s attempt=%s",
                reading_id,
                last_completion.provider,
                last_completion.model,
                context.prompt_version,
                attempts,
            )
            return ReadingGenerationResult(
                ReadingGenerationStatus.COMPLETED,
                result=validated.result,
                attempt_count=attempts,
                repair_used=attempts > 1,
                provider=last_completion.provider,
                model=last_completion.model,
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
        except ReadingPromptNotFoundError:
            return await self._fail(
                reading_id,
                user_id,
                "prompt_not_found",
                attempts,
                last_completion,
            )
        except InvalidReadingResult as error:
            return await self._fail(
                reading_id,
                user_id,
                f"reading_{error.code}",
                attempts,
                last_completion,
            )
        except LLMTimeoutError:
            return await self._fail(
                reading_id, user_id, "llm_timeout", attempts, last_completion
            )
        except LLMRateLimitError:
            return await self._fail(
                reading_id, user_id, "llm_rate_limited", attempts, last_completion
            )
        except LLMAuthenticationError:
            return await self._fail(
                reading_id,
                user_id,
                "llm_authentication_error",
                attempts,
                last_completion,
            )
        except LLMInvalidRequestError:
            return await self._fail(
                reading_id,
                user_id,
                "llm_invalid_request",
                attempts,
                last_completion,
            )
        except LLMTransientError:
            return await self._fail(
                reading_id,
                user_id,
                "llm_transient_error",
                attempts,
                last_completion,
            )
        except LLMUnexpectedError:
            return await self._fail(
                reading_id,
                user_id,
                "unexpected_provider_error",
                attempts,
                last_completion,
            )
        except (TypeError, ValueError):
            return await self._fail(
                reading_id,
                user_id,
                "invalid_generation_input",
                attempts,
                last_completion,
            )
        except Exception:
            return await self._fail(
                reading_id,
                user_id,
                "unexpected_pipeline_error",
                attempts,
                last_completion,
            )

    def _ready_result(self, claim: ReadingGenerationClaim) -> ReadingGenerationResult:
        if claim.ready is None:
            return ReadingGenerationResult(ReadingGenerationStatus.CORRUPTED_RESULT)
        try:
            payload = json.dumps(claim.ready.payload, ensure_ascii=False)
            validated = self._validator.validate(payload, list(claim.ready.symbols))
        except (InvalidReadingResult, TypeError, ValueError):
            return ReadingGenerationResult(ReadingGenerationStatus.CORRUPTED_RESULT)
        return ReadingGenerationResult(
            ReadingGenerationStatus.COMPLETED,
            result=validated.result,
            idempotent=True,
        )

    @staticmethod
    def _map_claim(
        status: ReadingGenerationClaimStatus,
    ) -> ReadingGenerationStatus | None:
        values = {
            ReadingGenerationClaimStatus.ALREADY_PROCESSING: (
                ReadingGenerationStatus.ALREADY_PROCESSING
            ),
            ReadingGenerationClaimStatus.NOT_READY: ReadingGenerationStatus.NOT_READY,
            ReadingGenerationClaimStatus.PERSONA_DISABLED: (
                ReadingGenerationStatus.PERSONA_DISABLED
            ),
            ReadingGenerationClaimStatus.DELETED: ReadingGenerationStatus.DELETED,
            ReadingGenerationClaimStatus.NOT_FOUND: ReadingGenerationStatus.NOT_FOUND,
            ReadingGenerationClaimStatus.CORRUPTED_RESULT: (
                ReadingGenerationStatus.CORRUPTED_RESULT
            ),
        }
        return values.get(status)

    @staticmethod
    def _expected_symbols(
        contexts: tuple[ReadingSymbolContext, ...],
    ) -> tuple[ReadingSymbolInput, ...]:
        positions = [item.symbol.position for item in contexts]
        if len(positions) != len(set(positions)):
            raise ValueError("duplicate generation symbol position")
        return tuple(item.symbol for item in contexts)

    @staticmethod
    def _load_prompts(version: str) -> ReadingPromptSet:
        return load_reading_prompts(version)

    @staticmethod
    def _user_prompt(
        context: object,
        symbol_contexts: tuple[ReadingSymbolContext, ...],
        prompts: ReadingPromptSet,
    ) -> str:
        generation = context
        payload = {
            "persona_code": generation.persona_code,
            "topic": generation.topic,
            "user_question": generation.question,
            "optional_context": generation.context,
            "selected_symbols": [
                {
                    "symbol_id": item.symbol.symbol_id,
                    "position": item.symbol.position,
                    "orientation": item.symbol.orientation.value,
                    "catalog_version": item.symbol.catalog_version,
                    "display_name": item.display_name,
                    "interpretation_theme": item.interpretation_theme,
                }
                for item in symbol_contexts
            ],
        }
        return (
            f"{prompts.request_instruction}\n\nINPUT_JSON:\n"
            f"{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
        )

    async def _fail(
        self,
        reading_id: UUID,
        user_id: UUID,
        failure_code: str,
        attempts: int,
        completion: LLMCompletion | None,
    ) -> ReadingGenerationResult:
        finalized = await self._store.fail_generation(reading_id, user_id, failure_code)
        if finalized is ReadingGenerationFinalizeStatus.DELETED:
            return ReadingGenerationResult(ReadingGenerationStatus.DELETED)
        if finalized is ReadingGenerationFinalizeStatus.NOT_FOUND:
            return ReadingGenerationResult(ReadingGenerationStatus.NOT_FOUND)
        logger.warning(
            "reading_generation_failed reading_id=%s provider=%s model=%s "
            "attempt=%s failure_code=%s finalize_status=%s",
            reading_id,
            completion.provider if completion else "unknown",
            completion.model if completion else "unknown",
            attempts,
            failure_code,
            finalized.value,
        )
        return ReadingGenerationResult(
            ReadingGenerationStatus.FAILED,
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
    ) -> ReadingGenerationResult:
        mapped = {
            ReadingGenerationFinalizeStatus.DELETED: ReadingGenerationStatus.DELETED,
            ReadingGenerationFinalizeStatus.NOT_FOUND: ReadingGenerationStatus.NOT_FOUND,
        }.get(status, ReadingGenerationStatus.FAILED)
        return ReadingGenerationResult(
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
