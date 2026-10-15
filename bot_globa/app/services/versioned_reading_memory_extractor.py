"""Prompt-versioned LLM extractor for consented reading memory."""

import json

from pydantic import ValidationError

from app.domain.memory_extraction import CompletedReadingMemorySnapshot, MemoryExtractionPayload
from app.prompts.memory_extraction import (
    MEMORY_EXTRACTION_PROMPT_VERSION,
    load_memory_extraction_prompts,
)
from app.providers.llm.base import LLMClient, LLMRequest
from app.services.reading_memory_extraction import InvalidMemoryExtractionError


class VersionedLLMReadingMemoryExtractor:
    """Keep extraction prompts immutable and visible in telemetry/provenance."""

    def __init__(
        self,
        llm: LLMClient,
        *,
        prompt_version: str = MEMORY_EXTRACTION_PROMPT_VERSION,
    ) -> None:
        self._llm = llm
        self._version = prompt_version

    @property
    def version(self) -> str:
        return self._version

    async def extract(
        self,
        snapshot: CompletedReadingMemorySnapshot,
    ) -> MemoryExtractionPayload:
        prompts = load_memory_extraction_prompts(self._version)
        payload = {
            "persona_code": snapshot.persona_code,
            "topic": snapshot.topic,
            "user_question": snapshot.question,
            "optional_context": snapshot.context,
            "completed_reading_result": snapshot.result,
        }
        completion = await self._llm.generate_structured(
            LLMRequest(
                system_prompt=prompts.system,
                user_prompt=prompts.request.format(
                    input_json=json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                ),
                schema=MemoryExtractionPayload.model_json_schema(),
                message_ids=(str(snapshot.reading_id),),
                participant_labels=(),
                telemetry_persona_code="memory_extraction",
                telemetry_prompt_version=self._version,
            )
        )
        try:
            return MemoryExtractionPayload.model_validate_json(completion.payload)
        except (ValidationError, TypeError, ValueError) as exc:
            raise InvalidMemoryExtractionError("invalid structured memory extraction") from exc
