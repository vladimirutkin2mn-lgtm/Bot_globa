"""Lease-based processing for durable reading memory extraction jobs."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.memory_models import ReadingMemoryExtractionJob
from app.domain.memory_extraction import MemoryExtractionOutcome
from app.providers.llm.base import (
    LLMAuthenticationError,
    LLMInvalidRequestError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMTransientError,
    LLMUnexpectedError,
)
from app.services.oracle_memory import MemoryConsentRequiredError, MemoryProvenanceError
from app.services.reading_memory_extraction import (
    InvalidMemoryExtraction,
    MemorySourceUnavailableError,
)

logger = logging.getLogger(__name__)


class ReadingMemoryExtractionJobStatus(StrEnum):
    PENDING = "pending"
    CLAIMED = "claimed"
    COMPLETED = "completed"
    SKIPPED_NO_CONSENT = "skipped_no_consent"
    SKIPPED_SOURCE_UNAVAILABLE = "skipped_source_unavailable"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ClaimedReadingMemoryExtractionJob:
    job_id: UUID
    claim_id: UUID
    reading_id: UUID
    user_id: UUID


class CompletedReadingExtractor(Protocol):
    async def extract_completed(
        self,
        reading_id: UUID,
        user_id: UUID,
    ) -> MemoryExtractionOutcome: ...


class ReadingMemoryExtractionJobWorker:
    """At-least-once external execution with idempotent durable persistence."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        extractor: CompletedReadingExtractor,
        *,
        lease_seconds: int = 120,
        retry_base_seconds: int = 30,
        max_attempts: int = 5,
    ) -> None:
        if lease_seconds < 1 or retry_base_seconds < 1 or max_attempts < 1:
            raise ValueError("memory extraction worker settings must be positive")
        self._sessions = sessions
        self._extractor = extractor
        self._lease_seconds = lease_seconds
        self._retry_base_seconds = retry_base_seconds
        self._max_attempts = max_attempts

    async def claim_one(self, worker_id: str) -> ClaimedReadingMemoryExtractionJob | None:
        if not worker_id:
            raise ValueError("memory extraction worker_id is required")
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            job = await session.scalar(
                select(ReadingMemoryExtractionJob)
                .where(
                    ReadingMemoryExtractionJob.available_at <= now,
                    or_(
                        ReadingMemoryExtractionJob.status
                        == ReadingMemoryExtractionJobStatus.PENDING.value,
                        (
                            ReadingMemoryExtractionJob.status
                            == ReadingMemoryExtractionJobStatus.CLAIMED.value
                        )
                        & (ReadingMemoryExtractionJob.lease_until < now),
                    ),
                )
                .order_by(
                    ReadingMemoryExtractionJob.available_at,
                    ReadingMemoryExtractionJob.created_at,
                )
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if job is None:
                return None
            claim_id = uuid4()
            job.status = ReadingMemoryExtractionJobStatus.CLAIMED.value
            job.claim_id = claim_id
            job.claimed_by = worker_id
            job.claimed_at = now
            job.lease_until = now + timedelta(seconds=self._lease_seconds)
            job.attempt_count += 1
            return ClaimedReadingMemoryExtractionJob(
                job_id=job.id,
                claim_id=claim_id,
                reading_id=job.reading_id,
                user_id=job.user_id,
            )

    async def run_once(self, worker_id: str) -> bool:
        claim = await self.claim_one(worker_id)
        if claim is None:
            return False
        try:
            await self._extractor.extract_completed(claim.reading_id, claim.user_id)
        except MemoryConsentRequiredError:
            await self._finish(
                claim,
                ReadingMemoryExtractionJobStatus.SKIPPED_NO_CONSENT,
                "memory_consent_required",
            )
        except (MemorySourceUnavailableError, MemoryProvenanceError, LookupError):
            await self._finish(
                claim,
                ReadingMemoryExtractionJobStatus.SKIPPED_SOURCE_UNAVAILABLE,
                "reading_source_unavailable",
            )
        except (LLMAuthenticationError, LLMInvalidRequestError):
            await self._finish(
                claim,
                ReadingMemoryExtractionJobStatus.FAILED,
                "memory_extractor_configuration",
            )
        except asyncio.CancelledError:
            raise
        except (
            InvalidMemoryExtraction,
            LLMTimeoutError,
            LLMRateLimitError,
            LLMTransientError,
            LLMUnexpectedError,
        ):
            await self._retry(claim, "memory_extraction_retryable")
        except Exception:
            logger.exception("reading_memory_extraction_job_unexpected job_id=%s", claim.job_id)
            await self._retry(claim, "unexpected_memory_extraction_error")
        else:
            await self._finish(claim, ReadingMemoryExtractionJobStatus.COMPLETED, None)
        return True

    async def _finish(
        self,
        claim: ClaimedReadingMemoryExtractionJob,
        status: ReadingMemoryExtractionJobStatus,
        error_code: str | None,
    ) -> bool:
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            job = await session.get(
                ReadingMemoryExtractionJob,
                claim.job_id,
                with_for_update=True,
            )
            if (
                job is None
                or job.status != ReadingMemoryExtractionJobStatus.CLAIMED.value
                or job.claim_id != claim.claim_id
            ):
                return False
            job.status = status.value
            job.claim_id = None
            job.lease_until = None
            job.last_error_code = error_code
            job.completed_at = now
            return True

    async def _retry(
        self,
        claim: ClaimedReadingMemoryExtractionJob,
        error_code: str,
    ) -> bool:
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            job = await session.get(
                ReadingMemoryExtractionJob,
                claim.job_id,
                with_for_update=True,
            )
            if (
                job is None
                or job.status != ReadingMemoryExtractionJobStatus.CLAIMED.value
                or job.claim_id != claim.claim_id
            ):
                return False
            job.claim_id = None
            job.claimed_by = None
            job.claimed_at = None
            job.lease_until = None
            if job.attempt_count >= self._max_attempts:
                job.status = ReadingMemoryExtractionJobStatus.FAILED.value
                job.last_error_code = "memory_extraction_retry_exhausted"
                job.completed_at = now
            else:
                job.status = ReadingMemoryExtractionJobStatus.PENDING.value
                job.last_error_code = error_code
                job.available_at = now + timedelta(
                    seconds=min(
                        self._retry_base_seconds * 2 ** (job.attempt_count - 1),
                        3600,
                    )
                )
                job.completed_at = None
            return True
