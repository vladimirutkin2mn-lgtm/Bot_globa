"""Prompt-pack-backed implementation of completed-reading memory extraction."""

import json

from pydantic import ValidationError

from app.domain.memory_extraction import (
    CURRENT_MEMORY_EXTRACTION_VERSION,
    CompletedReadingMemorySnapshot,
    MemoryExtractionPayload,
)
from app.prompts.reading_memory_extraction import (
    READING_MEMORY_EXTRACTION_PROMPT_VERSION,
    READING_MEMORY_EXTRACTION_REQUEST,
    READING_MEMORY_EXTRACTION_SYSTEM,
)
from app.providers.llm.base import LLMClient, LLMRequest
from app.services.reading_memory_extraction import InvalidMemoryExtractionError


class VersionedLLMReadingMemoryExtractor:
    """Structured extractor whose behavior is explicit and versioned outside service code."""

    def __init__(
        self,
        llm: LLMClient,
        *,
        version: str = CURRENT_MEMORY_EXTRACTION_VERSION,
    ) -> None:
        self._llm = llm
        self._version = version

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
        completion = await self._llm.generate_structured(
            LLMRequest(
                system_prompt=READING_MEMORY_EXTRACTION_SYSTEM,
                user_prompt=(
                    READING_MEMORY_EXTRACTION_REQUEST
                    + "\n\nINPUT_JSON:\n"
                    + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                ),
                schema=MemoryExtractionPayload.model_json_schema(),
                message_ids=(str(snapshot.reading_id),),
                participant_labels=(),
                telemetry_persona_code="oracle_memory_extraction",
                telemetry_prompt_version=READING_MEMORY_EXTRACTION_PROMPT_VERSION,
            )
        )
        try:
            return MemoryExtractionPayload.model_validate_json(completion.payload)
        except (ValidationError, TypeError, ValueError) as exc:
            raise InvalidMemoryExtractionError("invalid structured memory extraction") from exc
