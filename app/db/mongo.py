from functools import lru_cache

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import get_settings

_override_client: AsyncIOMotorClient | None = None


@lru_cache
def _default_client() -> AsyncIOMotorClient:
    settings = get_settings()
    return AsyncIOMotorClient(settings.MONGO_URI)


def get_client() -> AsyncIOMotorClient:
    if _override_client is not None:
        return _override_client
    return _default_client()


def set_client_override(client: AsyncIOMotorClient | None) -> None:
    """Test-only hook to swap in a mock Mongo client (e.g. mongomock-motor)."""
    global _override_client
    _override_client = client


def get_db() -> AsyncIOMotorDatabase:
    settings = get_settings()
    return get_client()[settings.MONGO_DB_NAME]


def users_col():
    return get_db()["users"]


def subscriptions_col():
    return get_db()["subscriptions"]


def transactions_col():
    return get_db()["transactions"]


def processed_payments_col():
    return get_db()["processed_payments"]


def oxapay_invoices_col():
    return get_db()["oxapay_invoices"]


def telegram_login_requests_col():
    return get_db()["telegram_login_requests"]
