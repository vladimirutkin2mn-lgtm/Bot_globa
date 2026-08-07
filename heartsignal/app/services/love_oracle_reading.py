"""Application use case for structured Love Oracle previews."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.db.reading_models import Reading
from app.domain.oracle_safety import (
    OracleInputSafetyClassifier,
    OracleInputSafetyResult,
    OracleRiskCategory,
    OracleSafetyAction,
)
from app.domain.persona import PersonaDefinition, PersonaEngine, persona_definition
from app.domain.reading import ReadingDraftRequest
from app.domain.reading_generation import ReadingSymbolContext
from app.services.preview_entitlement import PreviewOutcome, ReadingPreviewVisibility
from app.services.reading_generation import ReadingGenerationResult, ReadingGenerationService
from app.services.reading_service import ReadingService


class LoveOracleConfigurationError(RuntimeError):
    """The deployed Love Oracle definition is incompatible with this use case."""


class UnsupportedLoveOracleTopicError(ValueError):
    """The requested relationship topic is not enabled for Love Oracle v1."""


class UnsafeLoveOracleInputError(ValueError):
    """Safe refusal metadata without the private user payload."""

    def __init__(
        self,
        action: OracleSafetyAction,
        categories: tuple[OracleRiskCategory, ...],
    ) -> None:
        super().__init__(f"unsafe Love Oracle input: {action.value}")
        self.action = action
        self.categories = categories


class LoveOracleDraftService(Protocol):
    async def create_draft(self, user_id: UUID, request: ReadingDraftRequest) -> Reading: ...


class LoveOracleGenerationService(Protocol):
    async def generate_preview(
        self,
        reading_id: UUID,
        user_id: UUID,
        symbol_contexts: tuple[ReadingSymbolContext, ...],
    ) -> ReadingGenerationResult: ...


class LoveOraclePreviewEntitlement(Protocol):
    async def reserve_reading_preview(self, user_id: UUID, reading_id: UUID) -> PreviewOutcome: ...

    async def resolve_reading_visibility(
        self,
        user_id: UUID,
        reading_id: UUID,
    ) -> ReadingPreviewVisibility: ...


@dataclass(frozen=True, slots=True)
class LoveOraclePreviewRequest:
    topic: str
    question: str
    context: str | None = None


@dataclass(frozen=True, slots=True)
class LoveOraclePreviewOutcome:
    reading_id: UUID
    generation: ReadingGenerationResult
    visibility: ReadingPreviewVisibility = ReadingPreviewVisibility.PREVIEW


class LoveOracleReadingUseCase:
    """Create a safe relationship reading without inventing another person's inner state."""

    persona_code = "love_oracle"

    def __init__(
        self,
        readings: LoveOracleDraftService,
        generation: LoveOracleGenerationService,
        entitlements: LoveOraclePreviewEntitlement | None = None,
        safety_classifier: OracleInputSafetyClassifier | None = None,
    ) -> None:
        self._readings = readings
        self._generation = generation
        self._entitlements = entitlements
        self._safety = safety_classifier or OracleInputSafetyClassifier()
        self._persona = self._required_persona()

    @classmethod
    def from_services(
        cls,
        readings: ReadingService,
        generation: ReadingGenerationService,
        entitlements: LoveOraclePreviewEntitlement | None = None,
        safety_classifier: OracleInputSafetyClassifier | None = None,
    ) -> "LoveOracleReadingUseCase":
        """Production-friendly typed constructor without transport dependencies."""
        return cls(readings, generation, entitlements, safety_classifier)

    def classify_input(
        self,
        question: str,
        context: str | None = None,
    ) -> OracleInputSafetyResult:
        """Classify before transport emits any mystical processing state."""
        return self._safety.classify(question, context)

    async def create_preview(
        self,
        user_id: UUID,
        request: LoveOraclePreviewRequest,
    ) -> LoveOraclePreviewOutcome:
        self._validate_topic(request.topic)
        safety = self.classify_input(request.question, request.context)
        if not safety.may_reach_persona_prompt:
            raise UnsafeLoveOracleInputError(safety.action, safety.categories)
        reading = await self._readings.create_draft(
            user_id,
            ReadingDraftRequest(
                persona_code=self._persona.code,
                topic=request.topic,
                question=request.question,
                context=request.context,
                engine_version=self._persona.engine_version,
                prompt_version=self._persona.prompt_version,
                schema_version=self._persona.schema_version,
                cost_units=0,
            ),
        )
        return await self.generate_existing_preview(reading.id, user_id)

    async def generate_existing_preview(
        self,
        reading_id: UUID,
        user_id: UUID,
    ) -> LoveOraclePreviewOutcome:
        await self._reserve_if_possible(user_id, reading_id)
        generation = await self._generation.generate_preview(reading_id, user_id, ())
        visibility = (
            ReadingPreviewVisibility.PREVIEW
            if self._entitlements is None
            else await self._entitlements.resolve_reading_visibility(user_id, reading_id)
        )
        return LoveOraclePreviewOutcome(
            reading_id=reading_id,
            generation=generation,
            visibility=visibility,
        )

    async def _reserve_if_possible(self, user_id: UUID, reading_id: UUID) -> None:
        if self._entitlements is None:
            return
        outcome = await self._entitlements.reserve_reading_preview(user_id, reading_id)
        if outcome in {PreviewOutcome.USER_NOT_FOUND, PreviewOutcome.READING_NOT_FOUND}:
            raise LookupError("reading preview entitlement owner is unavailable")
        if outcome is PreviewOutcome.RELEASED_AFTER_FAILURE:
            await self._entitlements.reserve_reading_preview(user_id, reading_id)

    def _required_persona(self) -> PersonaDefinition:
        persona = persona_definition(self.persona_code)
        if persona is None:
            raise LoveOracleConfigurationError("Love Oracle persona is missing")
        if persona.engine is not PersonaEngine.SYMBOLIC:
            raise LoveOracleConfigurationError("Love Oracle must use a symbolic engine")
        if persona.schema_version != "reading-result-v1":
            raise LoveOracleConfigurationError("Love Oracle result schema is incompatible")
        return persona

    def _validate_topic(self, topic: str) -> None:
        if topic not in self._persona.supported_topics:
            raise UnsupportedLoveOracleTopicError("unsupported Love Oracle topic")
