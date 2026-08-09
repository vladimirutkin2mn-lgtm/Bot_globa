"""Deterministic, topic-neutral retrieval of consented memory for new readings."""

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.oracle_memory import MemoryClaimBasis, MemoryItemView, MemoryKind
from app.domain.reading_memory_context import (
    MemoryPromptUsageRecorder,
    ReadingMemoryContextItem,
)
from app.services.oracle_memory import OracleMemoryService
from app.services.oracle_memory_quality import memory_staleness_penalty

logger = logging.getLogger(__name__)

_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_STOP_WORDS = {
    "and",
    "are",
    "but",
    "for",
    "from",
    "have",
    "how",
    "into",
    "that",
    "the",
    "this",
    "what",
    "when",
    "where",
    "which",
    "with",
    "about",
    "будет",
    "быть",
    "для",
    "есть",
    "или",
    "как",
    "когда",
    "мне",
    "мой",
    "моя",
    "мои",
    "надо",
    "она",
    "они",
    "что",
    "чтобы",
    "это",
}
_TOPIC_KIND_WEIGHTS: dict[str, dict[MemoryKind, int]] = {
    "love": {
        MemoryKind.RELATIONSHIP_NOTES: 90,
        MemoryKind.RECURRING_THEME: 55,
        MemoryKind.PERSONAL_GOAL: 35,
        MemoryKind.USER_STATEMENT: 20,
    },
    "work": {
        MemoryKind.PERSONAL_GOAL: 85,
        MemoryKind.RECURRING_THEME: 55,
        MemoryKind.USER_STATEMENT: 30,
        MemoryKind.USER_PREFERENCE: 25,
    },
    "decision": {
        MemoryKind.PERSONAL_GOAL: 65,
        MemoryKind.USER_PREFERENCE: 50,
        MemoryKind.RECURRING_THEME: 45,
        MemoryKind.RELATIONSHIP_NOTES: 25,
        MemoryKind.USER_STATEMENT: 20,
    },
    "repeating_pattern": {
        MemoryKind.RECURRING_THEME: 95,
        MemoryKind.RELATIONSHIP_NOTES: 55,
        MemoryKind.PERSONAL_GOAL: 30,
        MemoryKind.USER_STATEMENT: 25,
    },
    "general_forecast": {
        MemoryKind.PERSONAL_GOAL: 45,
        MemoryKind.RECURRING_THEME: 45,
        MemoryKind.USER_PREFERENCE: 30,
        MemoryKind.USER_STATEMENT: 25,
        MemoryKind.RELATIONSHIP_NOTES: 20,
    },
}


@dataclass(frozen=True, slots=True)
class _RankedMemory:
    item: MemoryItemView
    score: int
    occurred_at: datetime


class OracleReadingMemoryRetriever:
    """Rank encrypted memory after consent checks, with no content-topic suppression."""

    def __init__(
        self,
        memory: OracleMemoryService,
        *,
        max_items: int = 6,
        max_item_characters: int = 600,
        max_total_characters: int = 2400,
        max_candidates: int = 100,
    ) -> None:
        if min(max_items, max_item_characters, max_total_characters, max_candidates) < 1:
            raise ValueError("reading memory retrieval limits must be positive")
        self._memory = memory
        self._max_items = max_items
        self._max_item_characters = max_item_characters
        self._max_total_characters = max_total_characters
        self._max_candidates = max_candidates

    async def retrieve(
        self,
        user_id: UUID,
        *,
        persona_code: str,
        topic: str,
        question: str,
        context: str | None,
    ) -> tuple[ReadingMemoryContextItem, ...]:
        del persona_code  # Reserved for persona-specific retrieval without changing the contract.
        active = await self._memory.list_active(user_id)
        if not active:
            return ()
        newest = sorted(active, key=lambda item: (item.created_at, item.id), reverse=True)
        query_tokens = self._tokens(" ".join((topic, question, context or "")))
        topic_weights = _TOPIC_KIND_WEIGHTS.get(topic, {})
        ranked: list[_RankedMemory] = []
        for item in newest[: self._max_candidates]:
            value_tokens = self._tokens(item.value)
            overlap = len(query_tokens.intersection(value_tokens))
            kind_weight = topic_weights.get(item.kind, 0)
            if item.kind is MemoryKind.ORACLE_PREFERENCE:
                kind_weight = max(kind_weight, 100)
            elif item.kind is MemoryKind.USER_PREFERENCE:
                kind_weight = max(kind_weight, 20)
            if overlap == 0 and kind_weight < 25:
                continue
            score = (
                kind_weight
                + overlap * 80
                + min(item.confidence_milli // 20, 50)
                + (20 if item.claim_basis is MemoryClaimBasis.USER_STATED else 0)
                - memory_staleness_penalty(item.kind, item.created_at)
            )
            ranked.append(
                _RankedMemory(
                    item=item,
                    score=score,
                    occurred_at=item.source_reading_created_at or item.created_at,
                )
            )
        ranked.sort(
            key=lambda candidate: (
                candidate.score,
                candidate.occurred_at,
                candidate.item.id,
            ),
            reverse=True,
        )

        selected: list[ReadingMemoryContextItem] = []
        selected_ids: list[UUID] = []
        used_characters = 0
        for candidate in ranked:
            if len(selected) >= self._max_items:
                break
            remaining = self._max_total_characters - used_characters
            if remaining < 1:
                break
            maximum = min(self._max_item_characters, remaining)
            value = self._truncate(candidate.item.value, maximum)
            selected.append(
                ReadingMemoryContextItem(
                    kind=candidate.item.kind,
                    claim_basis=candidate.item.claim_basis,
                    source_type=candidate.item.source_type,
                    value=value,
                    confidence_milli=candidate.item.confidence_milli,
                    created_at=candidate.item.created_at,
                    source_reading_created_at=candidate.item.source_reading_created_at,
                )
            )
            selected_ids.append(candidate.item.id)
            used_characters += len(value)
        await self._record_usage(user_id, selected_ids)
        return tuple(selected)

    async def _record_usage(self, user_id: UUID, item_ids: list[UUID]) -> None:
        if not item_ids or not isinstance(self._memory, MemoryPromptUsageRecorder):
            return
        try:
            await self._memory.record_prompt_use(user_id, item_ids)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "reading_memory_usage_record_failed selected_count=%s",
                len(item_ids),
            )

    @staticmethod
    def _tokens(value: str) -> set[str]:
        return {
            token
            for token in (match.group(0).casefold() for match in _TOKEN.finditer(value))
            if len(token) >= 3 and token not in _STOP_WORDS
        }

    @staticmethod
    def _truncate(value: str, maximum: int) -> str:
        if len(value) <= maximum:
            return value
        if maximum == 1:
            return "…"
        return value[: maximum - 1].rstrip() + "…"
