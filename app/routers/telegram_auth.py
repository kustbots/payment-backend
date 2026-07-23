from fastapi import APIRouter, Header, HTTPException, Request, status

from app.core.config import get_settings
from app.models.telegram_auth import TelegramLoginStartResponse, TelegramLoginStatusResponse
from app.services import telegram_auth_service

router = APIRouter(prefix="/api/auth/telegram", tags=["auth"])


@router.post("/start", response_model=TelegramLoginStartResponse)
async def start_telegram_login():
    """Public. Returns a one-time deep link -- show the user a "Continue with
    Telegram" button/instructions pointing at `deep_link`, then poll
    GET /status/{token} until it completes."""
    result = await telegram_auth_service.create_login_request()
    return TelegramLoginStartResponse(**result)


@router.get("/status/{token}", response_model=TelegramLoginStatusResponse)
async def telegram_login_status(token: str):
    result = await telegram_auth_service.get_login_status(token)
    return TelegramLoginStatusResponse(**result)


@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    """Telegram's server-to-server callback -- not for frontend use.
    Verified via the secret token Telegram echoes back on every update
    (configured when we call setWebhook at startup)."""
    if not telegram_auth_service.verify_webhook_secret(x_telegram_bot_api_secret_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook secret")

    update = await request.json()
    message = update.get("message") or {}
    text = message.get("text") or ""
    from_user = message.get("from") or {}

    settings = get_settings()
    parts = text.strip().split(maxsplit=1)
    valid_commands = {"/start", f"/start@{settings.TELEGRAM_AUTH_BOT_USERNAME}"}
    if len(parts) == 2 and parts[0] in valid_commands and from_user.get("id"):
        token = parts[1].strip()
        await telegram_auth_service.handle_telegram_start(token, from_user)

    return {"ok": True}
