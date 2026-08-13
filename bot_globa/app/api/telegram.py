"""Authenticated Telegram webhook transport."""

import hmac
import json
import logging
from typing import Annotated, cast

from aiogram import Bot
from aiogram.types import Update
from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.config import Settings
from app.services.telegram_stars_service import TelegramStarsPaymentService
from app.services.telegram_update_inbox import (
    TelegramAcceptOutcome,
    TelegramUpdateInboxService,
)

router = APIRouter(tags=["telegram"])
logger = logging.getLogger(__name__)


def _telegram_user_id(update: Update) -> int | None:
    if update.message is not None and update.message.from_user is not None:
        return update.message.from_user.id
    if update.callback_query is not None:
        return update.callback_query.from_user.id
    if update.pre_checkout_query is not None:
        return update.pre_checkout_query.from_user.id
    if update.subscription is not None:
        return update.subscription.user.id
    return None


@router.post("/telegram/webhook", status_code=status.HTTP_204_NO_CONTENT)
async def telegram_webhook(
    request: Request,
    telegram_secret: Annotated[str | None, Header(alias="X-Telegram-Bot-Api-Secret-Token")] = None,
) -> Response:
    """Authenticate updates; answer pre-checkout inline and durably enqueue the rest."""
    settings = cast("Settings", request.app.state.settings)
    if not settings.webhook_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    expected = settings.telegram_webhook_secret.get_secret_value()
    supplied = telegram_secret or ""
    if not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    max_bytes = cast("int", request.app.state.telegram_webhook_max_bytes)
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            declared_size = int(declared)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid request"
            ) from None
        if declared_size < 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid request")
        if declared_size > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Payload too large",
            )

    webhook_body = bytearray()
    async for chunk in request.stream():
        if len(webhook_body) + len(chunk) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Payload too large",
            )
        webhook_body.extend(chunk)
    try:
        raw_payload = json.loads(bytes(webhook_body))
        if not isinstance(raw_payload, dict):
            raise TypeError
        payload = cast("dict[str, object]", raw_payload)
        bot = cast("Bot", request.app.state.telegram_bot)
        update = Update.model_validate(payload, context={"bot": bot})
    except (json.JSONDecodeError, ValidationError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid update"
        ) from None

    if update.pre_checkout_query is not None:
        stars = cast(
            "TelegramStarsPaymentService",
            request.app.state.telegram_stars_service,
        )
        query = update.pre_checkout_query
        decision = await stars.validate_pre_checkout(
            query.from_user.id,
            query.id,
            query.invoice_payload,
            query.currency,
            query.total_amount,
        )
        response_payload: dict[str, object] = {
            "method": "answerPreCheckoutQuery",
            "pre_checkout_query_id": query.id,
            "ok": decision.approved,
        }
        if not decision.approved and decision.error_message is not None:
            response_payload["error_message"] = decision.error_message
        return JSONResponse(response_payload)

    inbox = cast("TelegramUpdateInboxService", request.app.state.telegram_update_inbox)
    accepted = await inbox.accept(update.update_id, _telegram_user_id(update), payload)
    if accepted.outcome is TelegramAcceptOutcome.PAYLOAD_MISMATCH:
        logger.warning("telegram_update_payload_mismatch update_id=%s", update.update_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
