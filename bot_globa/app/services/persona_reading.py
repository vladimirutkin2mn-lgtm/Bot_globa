"""One use case for every persona whose answer is a bounded structured reading.

The astrology persona is deliberately excluded: it needs a consented birth profile and a
calculation engine, so it keeps its own use case in `app.services.horoscope_reading`.
"""

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
from app.domain.persona import PersonaDefinition, persona_definition
from app.domain.reading import ReadingDraftRequest
from app.domain.reading_generation import ReadingSymbolContext
from app.services.preview_entitlement import PreviewOutcome, ReadingPreviewVisibility
from app.services.reading_generation import ReadingGenerationResult, ReadingGenerationService
from app.services.reading_service import ReadingService

READING_RESULT_SCHEMA_VERSION = "reading-result-v1"


class PersonaConfigurationError(RuntimeError):
    """The deployed persona definition is incompatible with this use case."""


class UnsupportedPersonaTopicError(ValueError):
    """The requested topic is not enabled for the persona."""

    def __init__(self, persona_code: str) -> None:
        super().__init__(f"unsupported topic for persona {persona_code}")
        self.persona_code = persona_code


class UnsafePersonaInputError(ValueError):
    """Safe refusal metadata without the private user payload."""

    def __init__(
        self,
        persona_code: str,
        action: OracleSafetyAction,
        categories: tuple[OracleRiskCategory, ...],
    ) -> None:
        super().__init__(f"unsafe {persona_code} input: {action.value}")
        self.persona_code = persona_code
        self.action = action
        self.categories = categories


class ReadingDraftStore(Protocol):
    async def create_draft(self, user_id: UUID, request: ReadingDraftRequest) -> Reading: ...


class ReadingPreviewGenerator(Protocol):
    async def generate_preview(
        self,
        reading_id: UUID,
        user_id: UUID,
        symbol_contexts: tuple[ReadingSymbolContext, ...],
    ) -> ReadingGenerationResult: ...


class ReadingPreviewEntitlement(Protocol):
    async def reserve_reading_preview(self, user_id: UUID, reading_id: UUID) -> PreviewOutcome: ...

    async def resolve_reading_visibility(
        self,
        user_id: UUID,
        reading_id: UUID,
    ) -> ReadingPreviewVisibility: ...


class SymbolDrawer(Protocol):
    """Deterministic symbols the model explains but never invents.

    `version` is frozen on the reading as its engine version, so a redraw for the same
    reading must keep returning the same symbols.
    """

    version: str
    set_code: str

    def draw(self, reading_id: UUID) -> tuple[ReadingSymbolContext, ...]: ...


@dataclass(frozen=True, slots=True)
class PersonaPreviewRequest:
    topic: str
    question: str
    context: str | None = None


@dataclass(frozen=True, slots=True)
class PersonaPreviewOutcome:
    reading_id: UUID
    generation: ReadingGenerationResult
    symbols: tuple[ReadingSymbolContext, ...] = ()
    symbol_set_code: str | None = None
    visibility: ReadingPreviewVisibility = ReadingPreviewVisibility.PREVIEW


class PersonaReadingUseCase:
    """Classify, draft, draw and generate one persona preview."""

    def __init__(
        self,
        persona_code: str,
        readings: ReadingDraftStore,
        generation: ReadingPreviewGenerator,
        *,
        drawer: SymbolDrawer | None = None,
        entitlements: ReadingPreviewEntitlement | None = None,
        safety_classifier: OracleInputSafetyClassifier | None = None,
    ) -> None:
        self._persona = _required_persona(persona_code)
        self._readings = readings
        self._generation = generation
        self._drawer = drawer
        self._entitlements = entitlements
        self._safety = safety_classifier or OracleInputSafetyClassifier()

    @classmethod
    def from_services(
        cls,
        persona_code: str,
        readings: ReadingService,
        generation: ReadingGenerationService,
        *,
        drawer: SymbolDrawer | None = None,
        entitlements: ReadingPreviewEntitlement | None = None,
        safety_classifier: OracleInputSafetyClassifier | None = None,
    ) -> "PersonaReadingUseCase":
        """Production-friendly typed constructor without transport dependencies."""
        return cls(
            persona_code,
            readings,
            generation,
            drawer=drawer,
            entitlements=entitlements,
            safety_classifier=safety_classifier,
        )

    @property
    def persona(self) -> PersonaDefinition:
        return self._persona

    @property
    def persona_code(self) -> str:
        return self._persona.code

    def classify_input(self, question: str, context: str | None = None) -> OracleInputSafetyResult:
        """Classify before transport emits any mystical processing state."""
        return self._safety.classify(question, context)

    async def create_preview(
        self,
        user_id: UUID,
        request: PersonaPreviewRequest,
    ) -> PersonaPreviewOutcome:
        if request.topic not in self._persona.supported_topics:
            raise UnsupportedPersonaTopicError(self.persona_code)
        safety = self.classify_input(request.question, request.context)
        if not safety.may_reach_persona_prompt:
            raise UnsafePersonaInputError(self.persona_code, safety.action, safety.categories)
        reading = await self._readings.create_draft(
            user_id,
            ReadingDraftRequest(
                persona_code=self._persona.code,
                topic=request.topic,
                question=request.question,
                context=request.context,
                engine_version=self._engine_version,
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
    ) -> PersonaPreviewOutcome:
        await self._reserve_if_possible(user_id, reading_id)
        symbols = () if self._drawer is None else self._drawer.draw(reading_id)
        generation = await self._generation.generate_preview(reading_id, user_id, symbols)
        visibility = (
            ReadingPreviewVisibility.PREVIEW
            if self._entitlements is None
            else await self._entitlements.resolve_reading_visibility(user_id, reading_id)
        )
        return PersonaPreviewOutcome(
            reading_id=reading_id,
            generation=generation,
            symbols=symbols,
            symbol_set_code=None if self._drawer is None else self._drawer.set_code,
            visibility=visibility,
        )

    @property
    def _engine_version(self) -> str:
        if self._drawer is None:
            return self._persona.engine_version
        return self._drawer.version

    async def _reserve_if_possible(self, user_id: UUID, reading_id: UUID) -> None:
        if self._entitlements is None:
            return
        outcome = await self._entitlements.reserve_reading_preview(user_id, reading_id)
        if outcome in {PreviewOutcome.USER_NOT_FOUND, PreviewOutcome.READING_NOT_FOUND}:
            raise LookupError("reading preview entitlement owner is unavailable")
        if outcome is PreviewOutcome.RELEASED_AFTER_FAILURE:
            await self._entitlements.reserve_reading_preview(user_id, reading_id)


def _required_persona(code: str) -> PersonaDefinition:
    persona = persona_definition(code)
    if persona is None:
        raise PersonaConfigurationError(f"persona {code} is missing")
    if persona.requires_calculation_engine:
        raise PersonaConfigurationError(f"persona {code} requires the astrology use case")
    if persona.schema_version != READING_RESULT_SCHEMA_VERSION:
        raise PersonaConfigurationError(f"persona {code} result schema is incompatible")
    return persona
