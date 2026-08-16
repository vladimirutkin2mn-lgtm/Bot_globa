"""Vertical coverage for draft, deterministic draw and structured persona previews."""

import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import User
from app.db.reading_models import Persona, Reading
from app.domain.reading import ReadingAccess, ReadingDraftRequest, ReadingStatus
from app.domain.reading_generation import ReadingSymbolContext
from app.providers.llm.base import LLMCompletion, LLMRequest
from app.repositories.reading_generation import SqlAlchemyReadingGenerationStore
from app.services.persona_reading import (
    PersonaPreviewRequest,
    PersonaReadingUseCase,
    UnsupportedPersonaTopicError,
)
from app.services.reading_generation import (
    ReadingGenerationResult,
    ReadingGenerationService,
    ReadingGenerationStatus,
)
from app.services.reading_service import ReadingService
from app.services.sensitive_content import AESGCMSensitiveContentCipher
from app.services.symbolic_engine import TarotSymbolDrawer


class CapturingDraftService:
    def __init__(self) -> None:
        self.reading_id = uuid4()
        self.requests: list[tuple[UUID, ReadingDraftRequest]] = []

    async def create_draft(self, user_id: UUID, request: ReadingDraftRequest) -> Reading:
        self.requests.append((user_id, request))
        return Reading(id=self.reading_id)

    async def load_symbol_contract(
        self,
        reading_id: UUID,
        user_id: UUID,
    ) -> tuple[str, str] | None:
        del user_id
        if reading_id != self.reading_id or not self.requests:
            return None
        request = self.requests[-1][1]
        return request.engine_version, request.symbol_set_code


class CapturingGenerationService:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID, tuple[ReadingSymbolContext, ...]]] = []

    async def generate_preview(
        self,
        reading_id: UUID,
        user_id: UUID,
        symbol_contexts: tuple[ReadingSymbolContext, ...],
    ) -> ReadingGenerationResult:
        self.calls.append((reading_id, user_id, symbol_contexts))
        return ReadingGenerationResult(ReadingGenerationStatus.COMPLETED)


class StructuredTarotLLM:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def generate_structured(self, request: LLMRequest) -> LLMCompletion:
        self.requests.append(request)
        input_json = request.user_prompt.split("INPUT_JSON:\n", 1)[1].split(
            "\n\nCORRECTION_INSTRUCTION:",
            1,
        )[0]
        source = json.loads(input_json)
        symbols = source["selected_symbols"]
        payload = {
            "title": "A structured reflection on the current choice",
            "opening": "The spread highlights direction, trade-offs and a practical pause.",
            "symbols": [
                {
                    "symbol_id": symbol["symbol_id"],
                    "position": symbol["position"],
                    "orientation": symbol["orientation"],
                    "interpretation": (
                        f"{symbol['display_name']} points to {symbol['interpretation_theme']}."
                    ),
                }
                for symbol in symbols
            ],
            "patterns": ["The decision benefits from separating urgency from importance."],
            "possible_scenarios": [
                {
                    "scenario": "A short pause makes the trade-offs easier to compare.",
                    "conditions": ["List what is reversible in each option."],
                }
            ],
            "reflection_questions": ["Which option better matches the value to protect?"],
            "practical_step": "Write one reversible next action for each option.",
            "uncertainty_note": "The cards cannot determine external events or guarantees.",
            "share_card": {
                "headline": "Your choice asks for deliberate direction",
                "short_text": "Separate urgency from what matters most.",
            },
            "safety": {"high_risk_detected": False, "categories": []},
        }
        return LLMCompletion(
            payload=json.dumps(payload),
            provider="structured-fake",
            model="tarot-vertical-test",
        )


async def test_use_case_freezes_versions_and_passes_topic_specific_symbols() -> None:
    drafts = CapturingDraftService()
    generation = CapturingGenerationService()
    use_case = PersonaReadingUseCase("tarot_reader", drafts, generation, drawer=TarotSymbolDrawer())
    user_id = uuid4()

    first = await use_case.create_preview(
        user_id,
        PersonaPreviewRequest(
            topic="decision",
            question="Which option deserves a slower review?",
            context="Both options can be reversed.",
        ),
    )
    replay = await use_case.generate_existing_preview(first.reading_id, user_id)

    assert len(drafts.requests) == 1
    _, request = drafts.requests[0]
    assert request.persona_code == "tarot_reader"
    assert request.engine_version == "tarot-symbolic-v2"
    assert request.prompt_version == "tarot-reader-v4"
    assert request.schema_version == "reading-result-v1"
    assert request.symbol_set_code == "decision_five_v1"
    assert request.cost_units == 0
    assert first.symbol_set_code == "decision_five_v1"
    assert first.symbols == replay.symbols
    assert len(first.symbols) == 5
    assert tuple(item.symbol.position for item in first.symbols) == (
        "decision_core",
        "option_a_potential",
        "option_a_cost",
        "option_b_potential",
        "option_b_cost",
    )
    assert len(generation.calls) == 2
    assert generation.calls[0][2] == first.symbols
    assert all(item.display_name and item.interpretation_theme for item in first.symbols)
    assert all("tradition=Rider-Waite-Smith" in item.interpretation_theme for item in first.symbols)
    assert all("position_focus=" in item.interpretation_theme for item in first.symbols)


async def test_a_replay_on_a_fresh_process_still_reveals_the_frozen_spread() -> None:
    """The spread has to survive a restart, so it is read back rather than remembered.

    A second worker — or this one after a deploy — never saw `create_draft`, so anything
    the drafting use case kept in memory is gone. Persistence is the only thing that can
    still say which layout the user was already shown.
    """

    drafts = CapturingDraftService()
    drafting = PersonaReadingUseCase(
        "tarot_reader", drafts, CapturingGenerationService(), drawer=TarotSymbolDrawer()
    )
    user_id = uuid4()
    reading_id = await drafting.create_draft(
        user_id,
        PersonaPreviewRequest(topic="love", question="What keeps this connection uneven?"),
    )

    restarted = PersonaReadingUseCase(
        "tarot_reader", drafts, CapturingGenerationService(), drawer=TarotSymbolDrawer()
    )
    symbols = await restarted.draw_symbols(reading_id, user_id)

    assert await drafting.draw_symbols(reading_id, user_id) == symbols
    assert tuple(item.symbol.position for item in symbols) == (
        "relationship_dynamic",
        "bond_or_attraction",
        "distance_or_friction",
        "unspoken_factor",
        "relationship_direction",
    )


async def test_a_symbolic_reading_without_a_frozen_code_is_refused_not_guessed() -> None:
    """A row drafted before the contract existed must fail loudly, never draw a default."""

    drafts = CapturingDraftService()
    use_case = PersonaReadingUseCase(
        "tarot_reader", drafts, CapturingGenerationService(), drawer=TarotSymbolDrawer()
    )
    user_id = uuid4()

    with pytest.raises(LookupError, match="symbol contract is unavailable"):
        await use_case.draw_symbols(uuid4(), user_id)

    await use_case.create_draft(
        user_id, PersonaPreviewRequest(topic="love", question="Where does this stall?")
    )
    drafts.requests[-1] = (
        user_id,
        drafts.requests[-1][1].model_copy(update={"symbol_set_code": "none"}),
    )

    with pytest.raises(ValueError, match="missing its frozen symbol set code"):
        await use_case.draw_symbols(drafts.reading_id, user_id)


async def test_unsupported_topic_is_rejected_before_draft_creation() -> None:
    drafts = CapturingDraftService()
    generation = CapturingGenerationService()
    use_case = PersonaReadingUseCase("tarot_reader", drafts, generation, drawer=TarotSymbolDrawer())

    with pytest.raises(
        UnsupportedPersonaTopicError, match="unsupported topic for persona tarot_reader"
    ):
        await use_case.create_preview(
            uuid4(),
            PersonaPreviewRequest(
                topic="medical_diagnosis",
                question="What illness do I have?",
            ),
        )

    assert not drafts.requests and not generation.calls


@pytest.mark.postgres
async def test_postgres_vertical_slice_persists_validated_preview_and_replays_without_llm(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    cipher = AESGCMSensitiveContentCipher("tarot-vertical-slice-key-material")
    async with payment_db.begin() as session:
        user = User(telegram_user_id=893001, first_name="TarotVertical")
        persona = Persona(
            code="tarot_reader",
            display_name="Tarot Reader",
            prompt_version="tarot-reader-v1",
            schema_version="reading-result-v1",
        )
        session.add_all((user, persona))
        await session.flush()

    readings = ReadingService(payment_db, cipher)
    llm = StructuredTarotLLM()
    generation = ReadingGenerationService(
        SqlAlchemyReadingGenerationStore(payment_db, cipher),
        llm,
    )
    use_case = PersonaReadingUseCase.from_services(
        "tarot_reader", readings, generation, drawer=TarotSymbolDrawer()
    )

    first = await use_case.create_preview(
        user.id,
        PersonaPreviewRequest(
            topic="decision",
            question="Should I choose speed or deeper learning?",
            context="Both options are reversible during the next month.",
        ),
    )
    # A fresh use-case instance has no in-memory set-code cache. Replaying through it proves
    # the spread is restored from the Reading rather than recomputed from current topic rules.
    restarted = PersonaReadingUseCase.from_services(
        "tarot_reader", readings, generation, drawer=TarotSymbolDrawer()
    )
    replay = await restarted.generate_existing_preview(first.reading_id, user.id)

    assert first.generation.status is ReadingGenerationStatus.COMPLETED
    assert not first.generation.idempotent
    assert replay.generation.status is ReadingGenerationStatus.COMPLETED
    assert replay.generation.idempotent
    assert replay.symbols == first.symbols
    assert replay.symbol_set_code == "decision_five_v1"
    assert len(llm.requests) == 1
    assert not llm.requests[0].repair
    assert "tradition=Rider-Waite-Smith" in llm.requests[0].user_prompt

    stored_result = await readings.load_result(first.reading_id, user.id)
    assert stored_result is not None
    assert stored_result["title"] == "A structured reflection on the current choice"
    async with payment_db() as session:
        reading = await session.get(Reading, first.reading_id)
        assert reading is not None
        assert reading.status == ReadingStatus.PREVIEW_READY.value
        assert reading.access_level == ReadingAccess.PREVIEW.value
        assert reading.engine_version == "tarot-symbolic-v2"
        assert reading.prompt_version == "tarot-reader-v4"
        assert reading.schema_version == "reading-result-v1"
        assert reading.symbol_set_code == "decision_five_v1"
