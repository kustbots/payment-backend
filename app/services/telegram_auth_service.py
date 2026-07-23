"""Telegram deep-link login: the frontend asks us for a login attempt, we
hand back a t.me deep link, the user opens it and taps Start in Telegram,
our bot webhook receives that /start and finishes the login/registration
automatically (no OTP code for the user to type anywhere), and the frontend
polls a status endpoint until it flips from "pending" to "completed" with
real access/refresh tokens.
"""

import secrets
from datetime import timedelta

import httpx

from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError
from app.core.logging import logger
from app.core.timeutils import utcnow
from app.db.mongo import telegram_login_requests_col, users_col
from app.models.user import TokenResponse, UserInDB
from app.services.auth_service import issue_tokens
from app.services.referral_service import generate_referral_code


def _bot_api_url(method: str) -> str:
    settings = get_settings()
    return f"https://api.telegram.org/bot{settings.TELEGRAM_AUTH_BOT_TOKEN}/{method}"


async def send_telegram_message(chat_id: int, text: str) -> None:
    settings = get_settings()
    if not settings.TELEGRAM_AUTH_BOT_TOKEN:
        return
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            await client.post(_bot_api_url("sendMessage"), json={"chat_id": chat_id, "text": text})
    except Exception as e:
        logger.warning(f"[TELEGRAM_AUTH] Failed to send confirmation message to {chat_id}: {e}")


async def register_webhook() -> None:
    """Called at app startup: point Telegram at our webhook so /start updates
    reach us. No-op if the bot isn't configured (e.g. local dev)."""
    settings = get_settings()
    if not settings.TELEGRAM_AUTH_BOT_TOKEN or not settings.TELEGRAM_WEBHOOK_BASE_URL:
        logger.info("[TELEGRAM_AUTH] Bot token or webhook base URL not configured, skipping setWebhook")
        return

    webhook_url = f"{settings.TELEGRAM_WEBHOOK_BASE_URL.rstrip('/')}/api/auth/telegram/webhook"
    payload = {"url": webhook_url, "allowed_updates": ["message"]}
    if settings.TELEGRAM_WEBHOOK_SECRET:
        payload["secret_token"] = settings.TELEGRAM_WEBHOOK_SECRET

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(_bot_api_url("setWebhook"), json=payload)
        logger.info(f"[TELEGRAM_AUTH] setWebhook -> {r.status_code}: {r.text}")
    except Exception as e:
        logger.warning(f"[TELEGRAM_AUTH] Failed to register webhook: {e}")


def verify_webhook_secret(provided: str | None) -> bool:
    settings = get_settings()
    if not settings.TELEGRAM_WEBHOOK_SECRET:
        # No secret configured (e.g. local dev without a public URL) -- accept.
        return True
    return provided == settings.TELEGRAM_WEBHOOK_SECRET


async def create_login_request() -> dict:
    settings = get_settings()
    if not settings.TELEGRAM_AUTH_BOT_USERNAME:
        raise ConflictError("Telegram login is not configured on this server yet")

    token = secrets.token_urlsafe(24)
    now = utcnow()
    doc = {
        "token": token,
        "status": "pending",
        "user_id": None,
        "telegram_user_id": None,
        "telegram_username": None,
        "created_at": now,
        "expires_at": now + timedelta(seconds=settings.TELEGRAM_LOGIN_TIMEOUT_SECONDS),
        "completed_at": None,
    }
    await telegram_login_requests_col().insert_one(doc)

    deep_link = f"https://t.me/{settings.TELEGRAM_AUTH_BOT_USERNAME}?start={token}"
    return {"token": token, "deep_link": deep_link, "expires_in": settings.TELEGRAM_LOGIN_TIMEOUT_SECONDS}


async def _find_or_create_telegram_user(telegram_user: dict) -> dict:
    telegram_user_id = telegram_user["id"]
    existing = await users_col().find_one({"telegram_user_id": telegram_user_id})
    if existing:
        # Keep the cached username/name fresh in case the user changed it.
        await users_col().update_one(
            {"_id": existing["_id"]},
            {"$set": {"telegram_username": telegram_user.get("username")}},
        )
        existing["telegram_username"] = telegram_user.get("username")
        return existing

    for _ in range(5):
        code = generate_referral_code()
        if not await users_col().find_one({"referral_code": code}):
            break
    else:
        code = generate_referral_code()

    now = utcnow()
    new_doc = {
        "email": None,
        "hashed_password": None,
        "points": 0.0,
        "role": "user",
        "referral_code": code,
        "referrer_id": None,
        "created_at": now,
        "is_active": True,
        "telegram_user_id": telegram_user_id,
        "telegram_username": telegram_user.get("username"),
    }
    result = await users_col().insert_one(new_doc)
    new_doc["_id"] = result.inserted_id
    return new_doc


async def handle_telegram_start(token: str, telegram_user: dict) -> None:
    """Called from the webhook when a /start <token> update arrives.
    Finds-or-creates the user from Telegram's own profile info and marks the
    login request completed. Silently ignores unknown/expired/already-used
    tokens (nothing meaningful to tell the Telegram update sender back)."""
    now = utcnow()
    request = await telegram_login_requests_col().find_one({"token": token})
    if not request:
        return
    if request["status"] != "pending" or request["expires_at"] < now:
        return

    user_doc = await _find_or_create_telegram_user(telegram_user)

    updated = await telegram_login_requests_col().find_one_and_update(
        {"token": token, "status": "pending"},
        {
            "$set": {
                "status": "completed",
                "user_id": user_doc["_id"],
                "telegram_user_id": telegram_user["id"],
                "telegram_username": telegram_user.get("username"),
                "completed_at": now,
            }
        },
    )
    if updated is not None:
        await send_telegram_message(
            telegram_user["id"],
            "✅ You're logged in! Head back to the app to continue.",
        )


async def get_login_status(token: str) -> dict:
    request = await telegram_login_requests_col().find_one({"token": token})
    if not request:
        raise NotFoundError("Unknown login token")

    if request["status"] == "completed":
        user_doc = await users_col().find_one({"_id": request["user_id"]})
        if not user_doc:
            return {"status": "expired"}
        tokens: TokenResponse = issue_tokens(UserInDB.from_mongo(user_doc))
        return {
            "status": "completed",
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "token_type": tokens.token_type,
        }

    if request["expires_at"] < utcnow():
        return {"status": "expired"}

    return {"status": "pending"}
