"""Print the Numa source/experiment decision report as JSON."""

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from app.config import get_settings
from app.db.session import create_engine, create_session_factory
from app.services.numa_decision_report import numa_decision_report


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Numa decision report")
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="UTC lookback window in days (default: 30)",
    )
    return parser.parse_args()


async def _run(days: int) -> None:
    if days <= 0:
        raise ValueError("days must be positive")
    settings = get_settings()
    engine = create_engine(str(settings.database_url))
    sessions = create_session_factory(engine)
    end_at = datetime.now(UTC)
    start_at = end_at - timedelta(days=days)
    try:
        async with sessions() as session:
            rows = await numa_decision_report(session, start_at=start_at, end_at=end_at)
        print(json.dumps([asdict(row) for row in rows], ensure_ascii=False, indent=2))
    finally:
        await engine.dispose()


def main() -> None:
    arguments = _arguments()
    asyncio.run(_run(arguments.days))


if __name__ == "__main__":
    main()
