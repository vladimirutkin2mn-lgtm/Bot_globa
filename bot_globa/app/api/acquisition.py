"""Public acquisition entry point that bridges Partizan tracking into Telegram."""

from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from app.acquisition import build_telegram_deep_link, referral_token_from_experiment
from app.config import Settings


def create_acquisition_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["acquisition"])

    @router.get("/", include_in_schema=False)
    async def acquisition_entry(ptz_experiment: UUID | None = None) -> RedirectResponse:
        if not settings.telegram_bot_username:
            raise HTTPException(status_code=503, detail="Telegram acquisition entry is not configured")
        token = referral_token_from_experiment(ptz_experiment) if ptz_experiment else None
        return RedirectResponse(
            build_telegram_deep_link(settings.telegram_bot_username, token),
            status_code=307,
        )

    return router
