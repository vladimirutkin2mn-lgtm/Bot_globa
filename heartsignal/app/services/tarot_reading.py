"""Application use case for creating deterministic structured tarot previews."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.db.reading_models import Reading
from app.domain.persona import PersonaDefinition, PersonaEngine, persona_definition
from app.domain.reading import ReadingDraftRequest
from app.domain.reading_generation import ReadingSymbolContext
from app.domain.tarot import THREE_CARD_SPREAD
from app.services.reading_generation import (
    ReadingGenerationResult,
    ReadingGenerationService,
)
from app.services.reading_service import ReadingService
from app.services.symbolic_engine import SelectedTarotCard, TarotSymbolicEngine


class TarotConfigurationError(RuntimeError):
    """The deployed tarot persona and engine versions are incompatible."""


class UnsupportedTarotTopicError(ValueError):
    """The requested topic is not enabled for the tarot MVP."""


class TarotDraftService(Protocol):
    async def create_draft(self, user_id: UUID, request: ReadingDraftRequest) -> Reading: ...


class TarotGenerationService(Protocol):
    async def generate_preview(
        self,
        reading_id: UUID,
        user_id: UUID,
        symbol_contexts: tuple[ReadingSymbolContext, ...],
    ) -> ReadingGenerationResult: ...


@dataclass(frozen=True, slots=True)
class TarotPreviewRequest:
    topic: str
    question: str
    context: str | None = None


@dataclass(frozen=True, slots=True)
class TarotPreviewOutcome:
    reading_id: UUID
    spread_code: str
    cards: tuple[SelectedTarotCard, ...]
    generation: ReadingGenerationResult


class TarotReadingUseCase:
    """Create a reading and generate its deterministic three-card preview."""

    persona_code = "tarot_reader"
    preview_spread_code = THREE_CARD_SPREAD.code

    def __init__(
        self,
        readings: TarotDraftService,
        generation: TarotGenerationService,
        engine: TarotSymbolicEngine | None = None,
    ) -> None:
        self._readings = readings
        self._generation = generation
        self._engine = engine or TarotSymbolicEngine()
        self._persona = self._required_persona()

    @classmethod
    def from_services(
        cls,
        readings: ReadingService,
        generation: ReadingGenerationService,
        engine: TarotSymbolicEngine | None = None,
    ) -> "TarotReadingUseCase":
        """Production-friendly typed constructor without transport dependencies."""

        return cls(readings, generation, engine)

    async def create_preview(
        self,
        user_id: UUID,
        request: TarotPreviewRequest,
    ) -> TarotPreviewOutcome:
        self._validate_topic(request.topic)
        reading = await self._readings.create_draft(
            user_id,
            ReadingDraftRequest(
                persona_code=self._persona.code,
                topic=request.topic,
                question=request.question,
                context=request.context,
                engine_version=self._engine.version,
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
    ) -> TarotPreviewOutcome:
        cards = self._engine.draw(reading_id, self.preview_spread_code)
        generation = await self._generation.generate_preview(
            reading_id,
            user_id,
            self._symbol_contexts(cards),
        )
        return TarotPreviewOutcome(
            reading_id=reading_id,
            spread_code=self.preview_spread_code,
            cards=cards,
            generation=generation,
        )

    def _required_persona(self) -> PersonaDefinition:
        persona = persona_definition(self.persona_code)
        if persona is None:
            raise TarotConfigurationError("tarot persona is missing")
        if persona.engine is not PersonaEngine.SYMBOLIC:
            raise TarotConfigurationError("tarot persona must use a symbolic engine")
        if persona.schema_version != "reading-result-v1":
            raise TarotConfigurationError("tarot result schema is incompatible")
        return persona

    def _validate_topic(self, topic: str) -> None:
        if topic not in self._persona.supported_topics:
            raise UnsupportedTarotTopicError("unsupported tarot topic")

    @staticmethod
    def _symbol_contexts(
        cards: tuple[SelectedTarotCard, ...],
    ) -> tuple[ReadingSymbolContext, ...]:
        return tuple(
            ReadingSymbolContext(
                symbol=card.to_reading_symbol(),
                display_name=card.card.name_ru,
                interpretation_theme=card.interpretation_theme,
            )
            for card in cards
        )
