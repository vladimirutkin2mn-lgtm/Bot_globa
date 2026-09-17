"""Public, cacheable visual assets used by Numa share flows."""

from datetime import date
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, Response

from app.services.daily_share_card import render_daily_share_card

router = APIRouter()

DAILY_SHARE_CARD_ROUTE = "/public/share/numa-daily-v1.jpg"
DAILY_SHARE_DYNAMIC_LEGACY_ROUTE = "/public/share/numa-daily-v3/{forecast_date}.jpg"
DAILY_SHARE_DYNAMIC_ROUTE = "/public/share/numa-daily-v5/{forecast_date}.jpg"
# Keep the legacy endpoint for old Telegram previews and already shared messages.
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
    """Return the stable legacy Numa share visual."""

    return FileResponse(
        DAILY_SHARE_CARD_PATH,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=604800, immutable"},
    )


def _render_dynamic_daily_share_card(forecast_date: date) -> Response:
    return Response(
        content=render_daily_share_card(forecast_date),
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.get(
    DAILY_SHARE_DYNAMIC_LEGACY_ROUTE,
    include_in_schema=False,
    name="numa_daily_share_card_v3",
    response_class=Response,
)
def numa_daily_share_card_v3(forecast_date: date) -> Response:
    """Keep previously shared v3 links reachable."""

    return _render_dynamic_daily_share_card(forecast_date)


@router.get(
    DAILY_SHARE_DYNAMIC_ROUTE,
    include_in_schema=False,
    name="numa_daily_share_card_v5",
    response_class=Response,
)
def numa_daily_share_card_v5(forecast_date: date) -> Response:
    """Return the current premium share card on a cache-versioned immutable URL."""

    return _render_dynamic_daily_share_card(forecast_date)
