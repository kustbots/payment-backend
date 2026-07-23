import pytest

from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError
from app.db.mongo import telegram_login_requests_col, users_col
from app.services import telegram_auth_service


@pytest.fixture(autouse=True)
def configure_bot(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "TELEGRAM_AUTH_BOT_USERNAME", "TestLoginBot")
    monkeypatch.setattr(settings, "TELEGRAM_AUTH_BOT_TOKEN", "")  # no real sendMessage calls in tests
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "test-webhook-secret")
    yield


@pytest.mark.asyncio
async def test_create_login_request_returns_deep_link():
    result = await telegram_auth_service.create_login_request()
    assert result["deep_link"] == f"https://t.me/TestLoginBot?start={result['token']}"
    assert result["expires_in"] > 0

    doc = await telegram_login_requests_col().find_one({"token": result["token"]})
    assert doc["status"] == "pending"


@pytest.mark.asyncio
async def test_create_login_request_fails_without_bot_username(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "TELEGRAM_AUTH_BOT_USERNAME", "")
    with pytest.raises(ConflictError):
        await telegram_auth_service.create_login_request()


@pytest.mark.asyncio
async def test_status_unknown_token_raises_not_found():
    with pytest.raises(NotFoundError):
        await telegram_auth_service.get_login_status("does-not-exist")


@pytest.mark.asyncio
async def test_full_login_flow_creates_new_user_and_issues_tokens():
    started = await telegram_auth_service.create_login_request()
    token = started["token"]

    pending_status = await telegram_auth_service.get_login_status(token)
    assert pending_status["status"] == "pending"

    telegram_user = {"id": 555111222, "username": "realuser", "first_name": "Real"}
    await telegram_auth_service.handle_telegram_start(token, telegram_user)

    completed_status = await telegram_auth_service.get_login_status(token)
    assert completed_status["status"] == "completed"
    assert completed_status["access_token"]
    assert completed_status["refresh_token"]

    user = await users_col().find_one({"telegram_user_id": 555111222})
    assert user is not None
    assert user["telegram_username"] == "realuser"
    assert user["email"] is None
    assert user["hashed_password"] is None


@pytest.mark.asyncio
async def test_second_login_reuses_existing_telegram_user():
    telegram_user = {"id": 999888777, "username": "repeatuser"}

    first = await telegram_auth_service.create_login_request()
    await telegram_auth_service.handle_telegram_start(first["token"], telegram_user)

    second = await telegram_auth_service.create_login_request()
    await telegram_auth_service.handle_telegram_start(second["token"], telegram_user)

    count = await users_col().count_documents({"telegram_user_id": 999888777})
    assert count == 1


@pytest.mark.asyncio
async def test_handle_start_ignores_unknown_token():
    # Should not raise -- unknown/garbage tokens are silently ignored since
    # this is invoked from an inbound Telegram webhook we don't control.
    await telegram_auth_service.handle_telegram_start("bogus-token", {"id": 1, "username": "x"})


@pytest.mark.asyncio
async def test_handle_start_does_not_reprocess_completed_request():
    telegram_user_a = {"id": 111, "username": "usera"}
    telegram_user_b = {"id": 222, "username": "userb"}

    started = await telegram_auth_service.create_login_request()
    await telegram_auth_service.handle_telegram_start(started["token"], telegram_user_a)

    # A second /start with the same (already-completed) token from a
    # different Telegram user must not hijack/overwrite the completed login.
    await telegram_auth_service.handle_telegram_start(started["token"], telegram_user_b)

    doc = await telegram_login_requests_col().find_one({"token": started["token"]})
    assert doc["telegram_user_id"] == 111


def test_verify_webhook_secret_matches():
    assert telegram_auth_service.verify_webhook_secret("test-webhook-secret") is True
    assert telegram_auth_service.verify_webhook_secret("wrong") is False
    assert telegram_auth_service.verify_webhook_secret(None) is False
