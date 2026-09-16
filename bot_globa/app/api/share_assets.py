"""Public, cacheable visual assets used by Numa share flows."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()

DAILY_SHARE_CARD_ROUTE = "/public/share/numa-daily-v1.jpg"
DAILY_SHARE_CARD_PATH = (
    Path(__file__).resolve().parents[1]
    / "bot"
    / "assets"
    / "share"
    / "numa_daily_share_v1.jpg"
)


@router.get(
    DAILY_SHARE_CARD_ROUTE,
    include_in_schema=False,
    name="numa_daily_share_card",
    response_class=FileResponse,
)
async def numa_daily_share_card() -> FileResponse:
    """Return the stable Numa share visual for Telegram link previews."""

    return FileResponse(
        DAILY_SHARE_CARD_PATH,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=604800, immutable"},
    )
