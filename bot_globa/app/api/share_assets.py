"""Public, cacheable visual assets used by Numa share flows."""

from datetime import date
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, Response

from app.services.daily_share_card import render_daily_share_card, render_daily_share_thumbnail

router = APIRouter()

DAILY_SHARE_CARD_ROUTE = "/public/share/numa-daily-v1.jpg"
DAILY_SHARE_DYNAMIC_LEGACY_ROUTE = "/public/share/numa-daily-v3/{forecast_date}.jpg"
DAILY_SHARE_DYNAMIC_V5_ROUTE = "/public/share/numa-daily-v5/{forecast_date}.jpg"
DAILY_SHARE_DYNAMIC_V6_ROUTE = "/public/share/numa-daily-v6/{forecast_date}.jpg"
DAILY_SHARE_DYNAMIC_PREVIOUS_ROUTE = "/public/share/numa-daily-v7/{forecast_date}.jpg"
DAILY_SHARE_DYNAMIC_ROUTE = "/public/share/numa-daily-v8/{forecast_date}.jpg"
DAILY_SHARE_THUMBNAIL_ROUTE = "/public/share/numa-daily-v8/{forecast_date}-thumb.jpg"
# Keep older endpoints for old Telegram previews and already shared messages.
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


def _jpeg_response(payload: bytes) -> Response:
    return Response(
        content=payload,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "Content-Length": str(len(payload)),
            "X-Content-Type-Options": "nosniff",
        },
    )


def _render_dynamic_daily_share_card(forecast_date: date) -> Response:
    return _jpeg_response(render_daily_share_card(forecast_date))


def _render_dynamic_daily_share_thumbnail(forecast_date: date) -> Response:
    return _jpeg_response(render_daily_share_thumbnail(forecast_date))


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
    DAILY_SHARE_DYNAMIC_V5_ROUTE,
    include_in_schema=False,
    name="numa_daily_share_card_v5",
    response_class=Response,
)
def numa_daily_share_card_v5(forecast_date: date) -> Response:
    """Keep previously shared v5 links reachable."""

    return _render_dynamic_daily_share_card(forecast_date)


@router.get(
    DAILY_SHARE_DYNAMIC_V6_ROUTE,
    include_in_schema=False,
    name="numa_daily_share_card_v6",
    response_class=Response,
)
def numa_daily_share_card_v6(forecast_date: date) -> Response:
    """Keep previously shared v6 links reachable."""

    return _render_dynamic_daily_share_card(forecast_date)


@router.get(
    DAILY_SHARE_DYNAMIC_PREVIOUS_ROUTE,
    include_in_schema=False,
    name="numa_daily_share_card_v7",
    response_class=Response,
)
def numa_daily_share_card_v7(forecast_date: date) -> Response:
    """Keep previously shared v7 links reachable."""

    return _render_dynamic_daily_share_card(forecast_date)


@router.get(
    DAILY_SHARE_DYNAMIC_ROUTE,
    include_in_schema=False,
    name="numa_daily_share_card_v8",
    response_class=Response,
)
def numa_daily_share_card_v8(forecast_date: date) -> Response:
    """Return the current baseline-JPEG share card on a cache-versioned URL."""

    return _render_dynamic_daily_share_card(forecast_date)


@router.get(
    DAILY_SHARE_THUMBNAIL_ROUTE,
    include_in_schema=False,
    name="numa_daily_share_thumbnail_v8",
    response_class=Response,
)
def numa_daily_share_thumbnail_v8(forecast_date: date) -> Response:
    """Return a small dedicated thumbnail for Telegram inline-result previews."""

    return _render_dynamic_daily_share_thumbnail(forecast_date)
