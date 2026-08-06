"""Application use case for calculated, fact-bound Horoscope previews."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.db.reading_models import Reading
from app.domain.horoscope import HoroscopeScope
from app.domain.oracle_safety import (
    OracleInputSafetyClassifier,
    OracleInputSafetyResult,
    OracleRiskCategory,
    OracleSafetyAction,
)
from app.domain.persona import PersonaDefinition, PersonaEngine, persona_definition
from app.domain.reading import ReadingDraftRequest
from app.services.horoscope_generation import (
    HoroscopeGenerationResult,
    HoroscopeGenerationService,
)
from app.services.preview_entitlement import PreviewOutcome, ReadingPreviewVisibility
from app.services.reading_service import ReadingService


class HoroscopeConfigurationError(RuntimeError):
    """The deployed astrologer definition is incompatible with this use case."""


class UnsupportedHoroscopeTopicError(ValueError):
    """The requested Horoscope topic is not enabled."""


class UnsafeHoroscopeInputError(ValueError):
    """Safe refusal metadata without private user text."""

    def __init__(
        self,
        action: OracleSafetyAction,
        categories: tuple[OracleRiskCategory, ...],
    ) -> None:
        super().__init__(f"unsafe Horoscope input: {action.value}")
        self.action = action
        self.categories = categories


class HoroscopeDraftService(Protocol):
    async def create_draft(self, user_id: UUID, request: ReadingDraftRequest) -> Reading: ...


class HoroscopePreviewGeneration(Protocol):
    async def generate_preview(
        self,
        reading_id: UUID,
        user_id: UUID,
    ) -> HoroscopeGenerationResult: ...


class HoroscopePreviewEntitlement(Protocol):
    async def reserve_reading_preview(self, user_id: UUID, reading_id: UUID) -> PreviewOutcome: ...

    async def resolve_reading_visibility(
        self,
        user_id: UUID,
        reading_id: UUID,
    ) -> ReadingPreviewVisibility: ...


@dataclass(frozen=True, slots=True)
class HoroscopePreviewRequest:
    topic: HoroscopeScope
    question: str
    context: str | None = None


@dataclass(frozen=True, slots=True)
class HoroscopePreviewOutcome:
    reading_id: UUID
    generation: HoroscopeGenerationResult
    visibility: ReadingPreviewVisibility = ReadingPreviewVisibility.PREVIEW


class HoroscopeReadingUseCase:
    """Create a safe Horoscope reading backed only by calculated chart facts."""

    persona_code = "astrologer"

    def __init__(
        self,
        readings: HoroscopeDraftService,
        generation: HoroscopePreviewGeneration,
        entitlements: HoroscopePreviewEntitlement | None = None,
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
        generation: HoroscopeGenerationService,
        entitlements: HoroscopePreviewEntitlement | None = None,
        safety_classifier: OracleInputSafetyClassifier | None = None,
    ) -> "HoroscopeReadingUseCase":
        return cls(readings, generation, entitlements, safety_classifier)

    def classify_input(
        self,
        question: str,
        context: str | None = None,
    ) -> OracleInputSafetyResult:
        """Classify before transport emits an astrology processing state."""

        return self._safety.classify(question, context)

    async def create_preview(
        self,
        user_id: UUID,
        request: HoroscopePreviewRequest,
    ) -> HoroscopePreviewOutcome:
        self._validate_topic(request.topic)
        safety = self.classify_input(request.question, request.context)
        if not safety.may_reach_persona_prompt:
            raise UnsafeHoroscopeInputError(safety.action, safety.categories)
        reading = await self._readings.create_draft(
            user_id,
            ReadingDraftRequest(
                persona_code=self._persona.code,
                topic=request.topic.value,
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
    ) -> HoroscopePreviewOutcome:
        await self._reserve_if_possible(user_id, reading_id)
        generation = await self._generation.generate_preview(reading_id, user_id)
        visibility = (
            ReadingPreviewVisibility.PREVIEW
            if self._entitlements is None
            else await self._entitlements.resolve_reading_visibility(user_id, reading_id)
        )
        return HoroscopePreviewOutcome(
            reading_id=reading_id,
            generation=generation,
            visibility=visibility,
        )

    async def _reserve_if_possible(self, user_id: UUID, reading_id: UUID) -> None:
        if self._entitlements is None:
            return
        outcome = await self._entitlements.reserve_reading_preview(user_id, reading_id)
        if outcome in {PreviewOutcome.USER_NOT_FOUND, PreviewOutcome.READING_NOT_FOUND}:
            raise LookupError("Horoscope preview entitlement owner is unavailable")
        if outcome is PreviewOutcome.RELEASED_AFTER_FAILURE:
            await self._entitlements.reserve_reading_preview(user_id, reading_id)

    @staticmethod
    def _required_persona() -> PersonaDefinition:
        persona = persona_definition("astrologer")
        if persona is None:
            raise HoroscopeConfigurationError("astrologer persona is missing")
        if persona.engine is not PersonaEngine.ASTROLOGY:
            raise HoroscopeConfigurationError("astrologer must use the astrology engine")
        if persona.engine_version != "astrology-calculation-v1":
            raise HoroscopeConfigurationError("astrologer engine version is incompatible")
        if persona.prompt_version != "astrologer-v1":
            raise HoroscopeConfigurationError("astrologer prompt version is incompatible")
        if persona.schema_version != "astrology-reading-result-v1":
            raise HoroscopeConfigurationError("astrologer result schema is incompatible")
        if not persona.requires_calculation_engine:
            raise HoroscopeConfigurationError("astrologer must require calculated facts")
        return persona

    def _validate_topic(self, topic: HoroscopeScope) -> None:
        if topic.value not in self._persona.supported_topics:
            raise UnsupportedHoroscopeTopicError("unsupported Horoscope topic")
