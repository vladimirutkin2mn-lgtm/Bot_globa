"""Public, cacheable visual assets used by Numa share flows."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()

DAILY_SHARE_CARD_ROUTE = "/public/share/numa-daily-v1.jpg"
# Reuse the full-size daily horoscope artwork that already ships with Numa. Keeping the
# public share endpoint stable lets Telegram cache the preview while avoiding a second,
# easy-to-drift copy of the same visual in the package.
DAILY_SHARE_CARD_PATH = (
    Path(__file__).resolve().parents[1] / "bot" / "assets" / "scenes" / "E-02.jpg"
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
