"""Public acquisition bridge from Partizan tracking into Telegram deep links."""

from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from app.services.acquisition_attribution import encode_partizan_start_payload

router = APIRouter(tags=["acquisition"])


@router.get("/", include_in_schema=False)
@router.get("/acquire/partizan", include_in_schema=False)
async def partizan_acquisition_redirect(
    request: Request,
    ptz_experiment: UUID | None = Query(default=None),
) -> RedirectResponse:
    """Redirect a validated Partizan experiment into a minimal Telegram start payload.

    Partizan may attach additional UTM/action query parameters to its destination. They are
    deliberately ignored here: Oracle carries only the experiment UUID across the Telegram
    boundary and persists only that first-touch identifier later in `/start`.
    """

    username = request.app.state.deployment_settings.telegram_bot_username
    if not username:
        raise HTTPException(
            status_code=503,
            detail="Telegram acquisition route is not configured",
        )

    destination = f"https://t.me/{quote(username, safe='')}"
    if ptz_experiment is not None:
        payload = encode_partizan_start_payload(ptz_experiment)
        destination = f"{destination}?start={quote(payload, safe='')}"

    response = RedirectResponse(url=destination, status_code=302)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response
