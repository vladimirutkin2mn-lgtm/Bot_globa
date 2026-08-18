"""Claim-fenced follow-up session included with an owned paid reading.

A paid full reading opens a 24-hour session with up to three follow-up questions.
Follow-ups explain the reading the user already paid for: they never draw new symbols,
never recalculate a chart and never charge again. Each attempt is reserved outside
provider I/O, and every terminal write is fenced by the claim ID that reserved it.
"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.reading_followups import ReadingFollowUp
from app.db.reading_models import Reading, ReadingPrivateContent
from app.domain.horoscope import AstrologyReadingResult
from app.domain.reading import ReadingAccess, ReadingStatus
from app.domain.reading_followup import (
    ReadingFollowUpAnswer,
    ReadingFollowUpQuestionInput,
    ReadingFollowUpResult,
    ReadingFollowUpSemanticError,
    allowed_reading_refs,
    validate_reading_followup_semantics,
)
from app.domain.reading_result import ReadingResult
from app.prompts.reading_followup import (
    ReadingFollowUpPromptNotFoundError,
    ReadingFollowUpPromptSet,
    load_reading_followup_prompts,
)
from app.providers.analytics import AnalyticsClient
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
from app.services.sensitive_content import (
    ContentPurpose,
    SensitiveContentCipher,
    SensitiveContentError,
)

logger = logging.getLogger(__name__)

READING_RESULT_SCHEMA = "reading-result-v1"
ASTROLOGY_RESULT_SCHEMA = "astrology-reading-result-v1"
MAX_SESSION_FOLLOW_UPS = 3
SESSION_WINDOW = timedelta(hours=24)


class ReadingFollowUpStatus(StrEnum):
    READY = "ready"
    PROCESSING = "processing"
    COMPLETED = "completed"
    EXPIRED = "expired"
    NOT_ELIGIBLE = "not_eligible"
    INVALID_QUESTION = "invalid_question"
    FAILED_RELEASED = "failed_released"
    CORRUPTED_HISTORY = "corrupted_history"


@dataclass(frozen=True, slots=True)
class ReadingFollowUpView:
    reading_id: UUID
    question: str
    answer: str
    limitations: tuple[str, ...]
    safety_high_risk: bool
    completed_at: datetime


@dataclass(frozen=True, slots=True)
class ReadingFollowUpResultView:
    status: ReadingFollowUpStatus
    view: ReadingFollowUpView | None = None
    failure_code: str | None = None
    idempotent: bool = False
    remaining_questions: int = 0
    session_expires_at: datetime | None = None


class _ReserveOutcome(StrEnum):
    CLAIMED = "claimed"
    PROCESSING = "processing"
    COMPLETED = "completed"
    EXPIRED = "expired"
    NOT_ELIGIBLE = "not_eligible"


@dataclass(frozen=True, slots=True)
class _Reservation:
    outcome: _ReserveOutcome
    claim_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class _Metadata:
    provider: str
    model: str
    attempts: int
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int | None
    provider_request_id: str | None


class ReadingFollowUpService:
    """Reserve outside provider I/O and fence every terminal write by claim ID."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        cipher: SensitiveContentCipher,
        llm: LLMClient,
        analytics: AnalyticsClient,
        provider: str,
        model: str,
        *,
        prompt_version: str = "reading_followup_v1",
        lease_seconds: int = 180,
        max_question_characters: int = 1000,
        max_repair_attempts: int = 1,
        prompt_loader: Callable[[str], ReadingFollowUpPromptSet] = load_reading_followup_prompts,
    ) -> None:
        self._sessions = sessions
        self._cipher = cipher
        self._llm = llm
        self._analytics = analytics
        self._provider = provider
        self._model = model
        self._prompt_version = prompt_version
        self._lease_seconds = lease_seconds
        self._max_question_characters = max_question_characters
        self._max_repairs = max_repair_attempts
        self._prompt_loader = prompt_loader

    async def inspect(self, reading_id: UUID, user_id: UUID) -> ReadingFollowUpResultView:
        async with self._sessions() as session:
            reading = await session.scalar(
                select(Reading).where(Reading.id == reading_id, Reading.user_id == user_id)
            )
            if not self._eligible(reading):
                return ReadingFollowUpResultView(ReadingFollowUpStatus.NOT_ELIGIBLE)

            expires_at = self._session_expires_at(reading)
            row = await session.scalar(
                select(ReadingFollowUp).where(ReadingFollowUp.reading_id == reading_id)
            )
            used = self._used_questions(row)
            remaining = max(MAX_SESSION_FOLLOW_UPS - used, 0)
            if expires_at <= datetime.now(UTC):
                return ReadingFollowUpResultView(
                    ReadingFollowUpStatus.EXPIRED,
                    remaining_questions=remaining,
                    session_expires_at=expires_at,
                )
            if row is None or row.status == "available":
                status = (
                    ReadingFollowUpStatus.READY
                    if remaining > 0
                    else ReadingFollowUpStatus.COMPLETED
                )
                return ReadingFollowUpResultView(
                    status,
                    remaining_questions=remaining,
                    session_expires_at=expires_at,
                )
            if row.status == "reserved":
                if row.lease_until is None or self._as_utc(row.lease_until) <= datetime.now(UTC):
                    return ReadingFollowUpResultView(
                        ReadingFollowUpStatus.READY,
                        remaining_questions=remaining,
                        session_expires_at=expires_at,
                    )
                return ReadingFollowUpResultView(
                    ReadingFollowUpStatus.PROCESSING,
                    remaining_questions=remaining,
                    session_expires_at=expires_at,
                )
            try:
                return ReadingFollowUpResultView(
                    ReadingFollowUpStatus.COMPLETED,
                    self._view(row),
                    idempotent=True,
                    remaining_questions=remaining,
                    session_expires_at=expires_at,
                )
            except (SensitiveContentError, ValidationError, ValueError, TypeError):
                logger.warning("reading_followup_history_corrupted reading_id=%s", reading_id)
                return ReadingFollowUpResultView(
                    ReadingFollowUpStatus.CORRUPTED_HISTORY,
                    remaining_questions=remaining,
                    session_expires_at=expires_at,
                )

    async def ask(
        self,
        reading_id: UUID,
        user_id: UUID,
        question: str,
    ) -> ReadingFollowUpResultView:
        try:
            parsed = ReadingFollowUpQuestionInput(question=question)
        except ValidationError:
            return ReadingFollowUpResultView(ReadingFollowUpStatus.INVALID_QUESTION)
        if len(parsed.question) > self._max_question_characters:
            return ReadingFollowUpResultView(ReadingFollowUpStatus.INVALID_QUESTION)

        reservation = await self._reserve(reading_id, user_id, parsed.question)
        if reservation.outcome is _ReserveOutcome.NOT_ELIGIBLE:
            return ReadingFollowUpResultView(ReadingFollowUpStatus.NOT_ELIGIBLE)
        if reservation.outcome is _ReserveOutcome.EXPIRED:
            return await self.inspect(reading_id, user_id)
        if reservation.outcome is _ReserveOutcome.PROCESSING:
            return ReadingFollowUpResultView(ReadingFollowUpStatus.PROCESSING)
        if reservation.outcome is _ReserveOutcome.COMPLETED:
            return await self.inspect(reading_id, user_id)
        claim_id = reservation.claim_id
        if claim_id is None:
            return ReadingFollowUpResultView(ReadingFollowUpStatus.PROCESSING)

        completions: list[LLMCompletion] = []
        attempts = 0
        try:
            result = await self._load_result(reading_id, user_id)
            if result is None:
                await self._release(reading_id, claim_id, "reading_not_eligible", 0, completions)
                return ReadingFollowUpResultView(ReadingFollowUpStatus.NOT_ELIGIBLE)
            prompts = self._prompt_loader(self._prompt_version)
            reading_json = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
            allowed = ",".join(sorted(allowed_reading_refs(result)))
            request = LLMRequest(
                prompts.system,
                prompts.request.format(
                    question=parsed.question,
                    reading_json=reading_json,
                    allowed_reading_refs=allowed,
                ),
                ReadingFollowUpAnswer.model_json_schema(),
                (str(reading_id),),
                (),
                telemetry_prompt_version=self._prompt_version,
            )
            completion = await self._llm.generate_structured(request)
            attempts += 1
            completions.append(completion)
            try:
                answer = self._validate(completion.payload, result)
            except (ValidationError, ValueError, ReadingFollowUpSemanticError) as error:
                if self._max_repairs == 0:
                    raise
                completion = await self._llm.generate_structured(
                    LLMRequest(
                        prompts.system,
                        prompts.repair.format(
                            question=parsed.question,
                            reading_json=reading_json,
                            allowed_reading_refs=allowed,
                            validation_errors=",".join(self._safe_errors(error)),
                            prior_output=completion.payload[:20_000],
                        ),
                        request.schema,
                        request.message_ids,
                        (),
                        repair=True,
                        telemetry_prompt_version=self._prompt_version,
                    )
                )
                attempts += 1
                completions.append(completion)
                answer = self._validate(completion.payload, result)
            metadata = self._metadata(completions, attempts)
            if not await self._complete(reading_id, user_id, claim_id, answer, metadata):
                return await self.inspect(reading_id, user_id)
            completed = await self.inspect(reading_id, user_id)
            await self._track(
                user_id,
                "reading_followup_completed",
                {
                    "reading_id": str(reading_id),
                    "prompt_version": self._prompt_version,
                    "attempt_count": str(attempts),
                    "repair_used": str(attempts > 1).lower(),
                    "remaining_questions": str(completed.remaining_questions),
                },
            )
            return completed
        except ReadingFollowUpPromptNotFoundError:
            code = "prompt_not_found"
        except (ValidationError, ValueError, ReadingFollowUpSemanticError):
            code = "invalid_model_output"
        except LLMTimeoutError:
            code = "llm_timeout"
        except LLMRateLimitError:
            code = "llm_rate_limited"
        except LLMAuthenticationError:
            code = "llm_authentication_error"
        except LLMInvalidRequestError:
            code = "llm_invalid_request"
        except LLMTransientError:
            code = "llm_transient_error"
        except LLMUnexpectedError:
            code = "unexpected_provider_error"
        except Exception:
            code = "unexpected_pipeline_error"
        await self._release(reading_id, claim_id, code, attempts, completions)
        await self._track(
            user_id,
            "reading_followup_failed_released",
            {"reading_id": str(reading_id), "failure_code": code},
        )
        logger.warning(
            "reading_followup_failed reading_id=%s prompt_version=%s failure_code=%s",
            reading_id,
            self._prompt_version,
            code,
        )
        return ReadingFollowUpResultView(
            ReadingFollowUpStatus.FAILED_RELEASED,
            failure_code=code,
        )

    async def _reserve(self, reading_id: UUID, user_id: UUID, question: str) -> _Reservation:
        encrypted_question = self._cipher.encrypt_json(
            ContentPurpose.READING_FOLLOW_UP_QUESTION,
            {"question": question},
        )
        now = datetime.now(UTC)
        claim_id = uuid4()
        async with self._sessions.begin() as session:
            reading = await session.scalar(
                select(Reading)
                .where(Reading.id == reading_id, Reading.user_id == user_id)
                .with_for_update()
            )
            if not self._eligible(reading):
                return _Reservation(_ReserveOutcome.NOT_ELIGIBLE)
            if self._session_expires_at(reading) <= now:
                return _Reservation(_ReserveOutcome.EXPIRED)
            row = await session.scalar(
                select(ReadingFollowUp)
                .where(ReadingFollowUp.reading_id == reading_id)
                .with_for_update()
            )
            used = self._used_questions(row)
            if used >= MAX_SESSION_FOLLOW_UPS:
                return _Reservation(_ReserveOutcome.COMPLETED)
            if (
                row is not None
                and row.status == "reserved"
                and row.lease_until is not None
                and self._as_utc(row.lease_until) > now
            ):
                return _Reservation(_ReserveOutcome.PROCESSING)
            lease_until = now + timedelta(seconds=self._lease_seconds)
            if row is None:
                session.add(
                    ReadingFollowUp(
                        reading_id=reading_id,
                        user_id=user_id,
                        status="reserved",
                        claim_id=claim_id,
                        lease_until=lease_until,
                        question_ciphertext=encrypted_question,
                        prompt_version=self._prompt_version,
                        reservation_count=1,
                    )
                )
            else:
                row.status = "reserved"
                row.claim_id = claim_id
                row.lease_until = lease_until
                row.question_ciphertext = encrypted_question
                row.answer_ciphertext = None
                row.prompt_version = self._prompt_version
                row.reservation_count = used + 1
                row.last_failure_code = None
                row.completed_at = None
            await session.flush()
            return _Reservation(_ReserveOutcome.CLAIMED, claim_id)

    async def _load_result(
        self,
        reading_id: UUID,
        user_id: UUID,
    ) -> ReadingFollowUpResult | None:
        async with self._sessions() as session:
            reading = await session.scalar(
                select(Reading).where(Reading.id == reading_id, Reading.user_id == user_id)
            )
            if reading is None or not self._eligible(reading):
                return None
            private = await session.get(ReadingPrivateContent, reading_id)
            if private is None or private.result_ciphertext is None:
                return None
            stored = self._cipher.decrypt_json(
                ContentPurpose.READING_RESULT,
                private.result_ciphertext,
            )
            payload = json.dumps(stored, ensure_ascii=False, separators=(",", ":"))
            if reading.schema_version == ASTROLOGY_RESULT_SCHEMA:
                return AstrologyReadingResult.model_validate_json(payload)
            if reading.schema_version == READING_RESULT_SCHEMA:
                return ReadingResult.model_validate_json(payload)
            return None

    async def _complete(
        self,
        reading_id: UUID,
        user_id: UUID,
        claim_id: UUID,
        answer: ReadingFollowUpAnswer,
        metadata: _Metadata,
    ) -> bool:
        encrypted_answer = self._cipher.encrypt_json(
            ContentPurpose.READING_FOLLOW_UP_ANSWER,
            answer.model_dump(mode="json"),
        )
        async with self._sessions.begin() as session:
            reading = await session.scalar(
                select(Reading)
                .where(Reading.id == reading_id, Reading.user_id == user_id)
                .with_for_update()
            )
            if not self._eligible(reading) or self._session_expires_at(reading) <= datetime.now(
                UTC
            ):
                return False
            row = await session.scalar(
                select(ReadingFollowUp)
                .where(ReadingFollowUp.reading_id == reading_id)
                .with_for_update()
            )
            if row is None or row.status != "reserved" or row.claim_id != claim_id:
                return False
            row.status = "completed"
            row.answer_ciphertext = encrypted_answer
            row.claim_id = None
            row.lease_until = None
            row.completed_at = datetime.now(UTC)
            row.last_failure_code = None
            self._apply_metadata(row, metadata)
            return True

    async def _release(
        self,
        reading_id: UUID,
        claim_id: UUID,
        code: str,
        attempts: int,
        completions: list[LLMCompletion],
    ) -> bool:
        """Give the session question back so provider failures never consume it."""
        metadata = self._metadata(completions, attempts)
        async with self._sessions.begin() as session:
            row = await session.scalar(
                select(ReadingFollowUp)
                .where(ReadingFollowUp.reading_id == reading_id)
                .with_for_update()
            )
            if row is None or row.status != "reserved" or row.claim_id != claim_id:
                return False
            row.status = "available"
            row.claim_id = None
            row.lease_until = None
            row.question_ciphertext = None
            row.answer_ciphertext = None
            row.completed_at = None
            row.last_failure_code = code
            row.reservation_count = max(int(row.reservation_count or 0) - 1, 0)
            self._apply_metadata(row, metadata)
            return True

    def _view(self, row: ReadingFollowUp) -> ReadingFollowUpView:
        if (
            row.question_ciphertext is None
            or row.answer_ciphertext is None
            or row.completed_at is None
        ):
            raise ValueError("reading followup content missing")
        question_payload = self._cipher.decrypt_json(
            ContentPurpose.READING_FOLLOW_UP_QUESTION,
            row.question_ciphertext,
        )
        answer_payload = self._cipher.decrypt_json(
            ContentPurpose.READING_FOLLOW_UP_ANSWER,
            row.answer_ciphertext,
        )
        if not isinstance(question_payload, dict) or not isinstance(
            question_payload.get("question"), str
        ):
            raise ValueError("reading followup question malformed")
        answer = ReadingFollowUpAnswer.model_validate(answer_payload)
        return ReadingFollowUpView(
            row.reading_id,
            question_payload["question"],
            answer.answer,
            tuple(answer.limitations),
            answer.safety.high_risk_detected,
            row.completed_at,
        )

    @staticmethod
    def _eligible(reading: Reading | None) -> bool:
        """A paid full reading owns one 24-hour follow-up session."""
        return bool(
            reading is not None
            and reading.status == ReadingStatus.FULL_READY.value
            and reading.access_level == ReadingAccess.FULL.value
            and reading.cost_units > 0
            and reading.full_access_transaction_id is not None
        )

    @staticmethod
    def _used_questions(row: ReadingFollowUp | None) -> int:
        if row is None:
            return 0
        return max(int(row.reservation_count or 0), 0)

    @classmethod
    def _session_expires_at(cls, reading: Reading | None) -> datetime:
        if reading is None:
            raise ValueError("reading is required for session expiry")
        started_at = reading.updated_at or reading.generated_at or reading.created_at
        return cls._as_utc(started_at) + SESSION_WINDOW

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _validate(payload: str, result: ReadingFollowUpResult) -> ReadingFollowUpAnswer:
        answer = ReadingFollowUpAnswer.model_validate_json(payload)
        validate_reading_followup_semantics(answer, result)
        return answer

    @staticmethod
    def _safe_errors(error: Exception) -> list[str]:
        """Return schema locations only; a provider payload may quote private text."""
        if isinstance(error, ReadingFollowUpSemanticError):
            return error.issues
        if isinstance(error, ValidationError):
            return [
                f"{'.'.join(str(part) for part in issue['loc'])}:{issue['type']}"
                for issue in error.errors()
            ][:8]
        return ["payload:invalid_json"]

    def _metadata(self, completions: list[LLMCompletion], attempts: int) -> _Metadata:
        last = completions[-1] if completions else None
        return _Metadata(
            provider=last.provider if last is not None else self._provider,
            model=last.model if last is not None else self._model,
            attempts=attempts,
            input_tokens=sum(c.input_tokens or 0 for c in completions) or None,
            output_tokens=sum(c.output_tokens or 0 for c in completions) or None,
            latency_ms=sum(c.latency_ms or 0 for c in completions) or None,
            provider_request_id=last.provider_request_id if last is not None else None,
        )

    @staticmethod
    def _apply_metadata(row: ReadingFollowUp, metadata: _Metadata) -> None:
        row.llm_attempt_count += metadata.attempts
        row.llm_provider = metadata.provider
        row.model_name = metadata.model
        row.provider_request_id = metadata.provider_request_id
        row.input_tokens = metadata.input_tokens
        row.output_tokens = metadata.output_tokens
        row.latency_ms = metadata.latency_ms

    async def _track(self, user_id: UUID, event: str, properties: dict[str, str]) -> None:
        try:
            await self._analytics.track(str(user_id), event, properties)
        except Exception:
            logger.warning("reading_followup_analytics_failed event=%s", event)
