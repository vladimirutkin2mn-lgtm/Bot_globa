"""Graceful worker for durable completed-reading memory extraction jobs."""

import asyncio
import logging
import signal
import socket

from app.config import Settings, get_settings
from app.db.session import create_engine, create_session_factory
from app.logging import configure_logging
from app.providers.llm.base import close_llm_client
from app.providers.llm.factory import create_llm_client
from app.services.oracle_memory import OracleMemoryService
from app.services.reading_memory_extraction import (
    LLMReadingMemoryExtractor,
    ReadingMemoryExtractionService,
)
from app.services.reading_memory_extraction_jobs import ReadingMemoryExtractionJobWorker
from app.services.sensitive_content import AESGCMSensitiveContentCipher, decode_configured_key

logger = logging.getLogger(__name__)


async def run(settings: Settings | None = None, stop: asyncio.Event | None = None) -> None:
    """Process durable extraction jobs until SIGTERM/SIGINT."""

    resolved = settings or get_settings()
    configure_logging(resolved.log_level)
    engine = create_engine(str(resolved.database_url))
    sessions = create_session_factory(engine)
    cipher = AESGCMSensitiveContentCipher(
        decode_configured_key(resolved.content_encryption_key.get_secret_value())
    )
    llm = create_llm_client(resolved)
    memory = OracleMemoryService(sessions, cipher)
    extraction = ReadingMemoryExtractionService(
        sessions,
        cipher,
        memory,
        LLMReadingMemoryExtractor(llm),
    )
    jobs = ReadingMemoryExtractionJobWorker(sessions, extraction)
    stopped = stop or asyncio.Event()
    worker_id = f"{socket.gethostname()}:{id(stopped)}"
    loop = asyncio.get_running_loop()
    if stop is None:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stopped.set)
    try:
        while not stopped.is_set():
            try:
                worked = await jobs.run_once(worker_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("oracle_memory_worker_iteration_failed")
                worked = False
            if not worked:
                try:
                    await asyncio.wait_for(stopped.wait(), timeout=1.0)
                except TimeoutError:
                    pass
    finally:
        try:
            await close_llm_client(llm)
        finally:
            await engine.dispose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
