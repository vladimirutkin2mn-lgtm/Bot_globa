"""Extract durable encrypted memory from completed readings with explicit consent."""

import json
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.memory_models import OracleMemoryConsent
from app.db.models import User
from app.db.reading_models import Persona, Reading, ReadingPrivateContent
from app.domain.horoscope import ASTROLOGY_READING_SCHEMA_VERSION
from app.domain.memory_extraction import (
    CURRENT_MEMORY_EXTRACTION_VERSION,
    CompletedReadingMemorySnapshot,
    MemoryExtractionOutcome,
    MemoryExtractionPayload,
    MemoryExtractionStatus,
)
from app.domain.oracle_memory import (
    CURRENT_MEMORY_CONSENT_VERSION,
    MemoryConsentStatus,
    MemoryCreateRequest,
    MemorySourceType,
)
from app.domain.reading import ReadingStatus
from app.prompts.memory_extraction import (
    MEMORY_EXTRACTION_PROMPT_VERSION,
    load_memory_extraction_prompts,
)
from app.providers.llm.base import LLMClient, LLMRequest
from app.services.horoscope_storage import (
    InvalidStoredHoroscopeError,
    horoscope_memory_source,
)
from app.services.oracle_memory import (
    MemoryConsentRequiredError,
    MemoryProvenanceError,
    OracleMemoryService,
)
from app.services.sensitive_content import (
    ContentPurpose,
    FingerprintingSensitiveContentCipher,
)


class InvalidMemoryExtractionError(ValueError):
    """Safe validation error that never includes generated or private text."""


class MemorySourceUnavailableError(LookupError):
    """The completed reading exists but its retained private payload is unavailable."""


class ReadingMemoryExtractor(Protocol):
    @property
    def version(self) -> str: ...

    async def extract(
        self,
        snapshot: CompletedReadingMemorySnapshot,
    ) -> MemoryExtractionPayload: ...


class LLMReadingMemoryExtractor:
    """Provider-neutral structured extractor backed by a frozen prompt pack."""

    def __init__(
        self,
        llm: LLMClient,
        *,
        version: str = CURRENT_MEMORY_EXTRACTION_VERSION,
        prompt_version: str = MEMORY_EXTRACTION_PROMPT_VERSION,
    ) -> None:
        self._llm = llm
        self._version = version
        self._prompt_version = prompt_version

    @property
    def version(self) -> str:
        return self._version

    async def extract(
        self,
        snapshot: CompletedReadingMemorySnapshot,
    ) -> MemoryExtractionPayload:
        payload = {
            "persona_code": snapshot.persona_code,
            "topic": snapshot.topic,
            "user_question": snapshot.question,
            "optional_context": snapshot.context,
            "completed_reading_result": snapshot.result,
        }
        prompts = load_memory_extraction_prompts(self._prompt_version)
        input_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        completion = await self._llm.generate_structured(
            LLMRequest(
                system_prompt=prompts.system,
                user_prompt=prompts.request.format(input_json=input_json),
                schema=MemoryExtractionPayload.model_json_schema(),
                message_ids=(str(snapshot.reading_id),),
                participant_labels=(),
                telemetry_persona_code="oracle_memory_extraction",
                telemetry_prompt_version=prompts.version,
            )
        )
        try:
            return MemoryExtractionPayload.model_validate_json(completion.payload)
        except (ValidationError, TypeError, ValueError) as exc:
            raise InvalidMemoryExtractionError("invalid structured memory extraction") from exc


class ReadingMemoryExtractionService:
    """Consent-gated two-phase extraction with a transactional persistence recheck."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        cipher: FingerprintingSensitiveContentCipher,
        memory: OracleMemoryService,
        extractor: ReadingMemoryExtractor,
        *,
        consent_version: str = CURRENT_MEMORY_CONSENT_VERSION,
    ) -> None:
        self._sessions = sessions
        self._cipher = cipher
        self._memory = memory
        self._extractor = extractor
        self._consent_version = consent_version

    async def extract_completed(
        self,
        reading_id: UUID,
        user_id: UUID,
    ) -> MemoryExtractionOutcome:
        snapshot = await self._load_snapshot(reading_id, user_id)
        extracted = await self._extractor.extract(snapshot)
        if not extracted.candidates:
            return MemoryExtractionOutcome(
                status=MemoryExtractionStatus.NO_CANDIDATES,
                extraction_version=self._extractor.version,
                created_count=0,
                skipped_count=0,
            )

        requests: dict[str, MemoryCreateRequest] = {}
        for candidate in extracted.candidates:
            candidate_key = self._cipher.fingerprint_json(
                ContentPurpose.ORACLE_MEMORY_VALUE,
                {
                    "reading_id": str(reading_id),
                    "extraction_version": self._extractor.version,
                    "kind": candidate.kind.value,
                    "claim_basis": candidate.claim_basis.value,
                    "value": candidate.value,
                },
            )
            request = MemoryCreateRequest(
                kind=candidate.kind,
                value=candidate.value,
                confidence_milli=candidate.confidence_milli,
                claim_basis=candidate.claim_basis,
                source_type=MemorySourceType.READING_DERIVED,
                source_reading_id=reading_id,
                source_persona_code=snapshot.persona_code,
                extraction_version=self._extractor.version,
                candidate_key=candidate_key,
            )
            previous = requests.get(candidate_key)
            if previous is not None and previous != request:
                raise InvalidMemoryExtractionError("conflicting memory candidate fingerprint")
            requests[candidate_key] = request

        created, skipped = await self._memory.remember_extracted_reading(
            user_id,
            reading_id,
            list(requests.values()),
        )
        return MemoryExtractionOutcome(
            status=MemoryExtractionStatus.COMPLETED,
            extraction_version=self._extractor.version,
            created_count=len(created),
            skipped_count=skipped + len(extracted.candidates) - len(requests),
        )

    async def _load_snapshot(
        self,
        reading_id: UUID,
        user_id: UUID,
    ) -> CompletedReadingMemorySnapshot:
        async with self._sessions.begin() as session:
            active_user = await session.scalar(
                select(User)
                .where(
                    User.id == user_id,
                    User.privacy_status == "active",
                )
                .with_for_update(of=User)
            )
            if active_user is None:
                raise LookupError("active oracle memory user not found")

            consent = await session.get(OracleMemoryConsent, user_id)
            if not (
                consent is not None
                and consent.status == MemoryConsentStatus.GRANTED.value
                and consent.consent_version == self._consent_version
            ):
                raise MemoryConsentRequiredError("explicit oracle memory consent is required")

            row = (
                await session.execute(
                    select(Reading, Persona, ReadingPrivateContent)
                    .join(Persona, Persona.id == Reading.persona_id)
                    .join(
                        ReadingPrivateContent,
                        ReadingPrivateContent.reading_id == Reading.id,
                    )
                    .where(
                        Reading.id == reading_id,
                        Reading.user_id == user_id,
                        Reading.status.in_(
                            (
                                ReadingStatus.PREVIEW_READY.value,
                                ReadingStatus.FULL_READY.value,
                            )
                        ),
                    )
                )
            ).one_or_none()
            if row is None:
                raise MemoryProvenanceError("owned completed source reading is unavailable")

            reading, persona, private = row
            if (
                private.question_ciphertext is None
                or private.result_ciphertext is None
                or private.content_deleted_at is not None
            ):
                raise MemorySourceUnavailableError(
                    "completed reading private source is unavailable"
                )

            question = self._cipher.decrypt_json(
                ContentPurpose.READING_QUESTION,
                private.question_ciphertext,
            )
            context = (
                self._cipher.decrypt_json(
                    ContentPurpose.READING_CONTEXT,
                    private.context_ciphertext,
                )
                if private.context_ciphertext is not None
                else None
            )
            result = self._cipher.decrypt_json(
                ContentPurpose.READING_RESULT,
                private.result_ciphertext,
            )
            if (
                not isinstance(question, str)
                or (context is not None and not isinstance(context, str))
                or not isinstance(result, dict)
                or not isinstance(persona.code, str)
            ):
                raise MemorySourceUnavailableError("completed reading private source is invalid")
            if reading.schema_version == ASTROLOGY_READING_SCHEMA_VERSION:
                try:
                    result = horoscope_memory_source(result)
                except InvalidStoredHoroscopeError as exc:
                    raise MemorySourceUnavailableError(
                        "completed astrology reading private source is invalid"
                    ) from exc
            return CompletedReadingMemorySnapshot(
                reading_id=reading.id,
                persona_code=persona.code,
                topic=reading.topic,
                question=question,
                context=context,
                result=result,
            )
