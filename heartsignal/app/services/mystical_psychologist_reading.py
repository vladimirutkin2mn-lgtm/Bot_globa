"""Application use case for structured Mystical Psychologist reflections."""

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


class MysticalPsychologistConfigurationError(RuntimeError):
    """The deployed reflective persona definition is incompatible with this use case."""


class UnsupportedMysticalPsychologistTopicError(ValueError):
    """The requested reflection topic is not enabled for this persona."""


class UnsafeMysticalPsychologistInputError(ValueError):
    """Safe refusal metadata without the private user payload."""

    def __init__(
        self,
        action: OracleSafetyAction,
        categories: tuple[OracleRiskCategory, ...],
    ) -> None:
        super().__init__(f"unsafe Mystical Psychologist input: {action.value}")
        self.action = action
        self.categories = categories


class MysticalPsychologistDraftService(Protocol):
    async def create_draft(self, user_id: UUID, request: ReadingDraftRequest) -> Reading: ...


class MysticalPsychologistGenerationService(Protocol):
    async def generate_preview(
        self,
        reading_id: UUID,
        user_id: UUID,
        symbol_contexts: tuple[ReadingSymbolContext, ...],
    ) -> ReadingGenerationResult: ...


class MysticalPsychologistPreviewEntitlement(Protocol):
    async def reserve_reading_preview(self, user_id: UUID, reading_id: UUID) -> PreviewOutcome: ...

    async def resolve_reading_visibility(
        self,
        user_id: UUID,
        reading_id: UUID,
    ) -> ReadingPreviewVisibility: ...


@dataclass(frozen=True, slots=True)
class MysticalPsychologistPreviewRequest:
    topic: str
    question: str
    context: str | None = None


@dataclass(frozen=True, slots=True)
class MysticalPsychologistPreviewOutcome:
    reading_id: UUID
    generation: ReadingGenerationResult
    visibility: ReadingPreviewVisibility = ReadingPreviewVisibility.PREVIEW


class MysticalPsychologistReadingUseCase:
    """Create a metaphorical self-reflection without diagnosis or therapeutic authority."""

    persona_code = "mystical_psychologist"

    def __init__(
        self,
        readings: MysticalPsychologistDraftService,
        generation: MysticalPsychologistGenerationService,
        entitlements: MysticalPsychologistPreviewEntitlement | None = None,
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
        entitlements: MysticalPsychologistPreviewEntitlement | None = None,
        safety_classifier: OracleInputSafetyClassifier | None = None,
    ) -> "MysticalPsychologistReadingUseCase":
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
        request: MysticalPsychologistPreviewRequest,
    ) -> MysticalPsychologistPreviewOutcome:
        self._validate_topic(request.topic)
        safety = self.classify_input(request.question, request.context)
        if not safety.may_reach_persona_prompt:
            raise UnsafeMysticalPsychologistInputError(safety.action, safety.categories)
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
    ) -> MysticalPsychologistPreviewOutcome:
        await self._reserve_if_possible(user_id, reading_id)
        generation = await self._generation.generate_preview(reading_id, user_id, ())
        visibility = (
            ReadingPreviewVisibility.PREVIEW
            if self._entitlements is None
            else await self._entitlements.resolve_reading_visibility(user_id, reading_id)
        )
        return MysticalPsychologistPreviewOutcome(
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
            raise MysticalPsychologistConfigurationError("Mystical Psychologist persona is missing")
        if persona.engine is not PersonaEngine.REFLECTIVE:
            raise MysticalPsychologistConfigurationError(
                "Mystical Psychologist must use a reflective engine"
            )
        if persona.schema_version != "reading-result-v1":
            raise MysticalPsychologistConfigurationError(
                "Mystical Psychologist result schema is incompatible"
            )
        return persona

    def _validate_topic(self, topic: str) -> None:
        if topic not in self._persona.supported_topics:
            raise UnsupportedMysticalPsychologistTopicError(
                "unsupported Mystical Psychologist topic"
            )
