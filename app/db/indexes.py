from pymongo import ASCENDING
from pymongo.errors import OperationFailure

from app.db.mongo import (
    oxapay_invoices_col,
    processed_payments_col,
    subscriptions_col,
    telegram_login_requests_col,
    transactions_col,
    users_col,
)

# Mongo error codes for "an index with this name already exists but with a
# different definition" -- raised when a field's index options change across
# a deploy (e.g. a plain unique index becomes a partial unique index).
_INDEX_CONFLICT_CODES = {85, 86}  # IndexOptionsConflict, IndexKeySpecsConflict


async def _ensure_index(collection, keys, **kwargs) -> None:
    """create_index that tolerates the index definition having changed since
    it was last created (drops and recreates it instead of crashing app
    startup)."""
    default_name = "_".join(f"{field}_{direction}" for field, direction in keys)
    try:
        await collection.create_index(keys, **kwargs)
    except OperationFailure as e:
        if e.code in _INDEX_CONFLICT_CODES:
            await collection.drop_index(default_name)
            await collection.create_index(keys, **kwargs)
        else:
            raise


async def create_indexes() -> None:
    # Partial (not plain) unique index: telegram-login-created accounts have
    # no email, and a plain unique index would reject more than one such
    # null email.
    await _ensure_index(
        users_col(),
        [("email", ASCENDING)],
        unique=True,
        partialFilterExpression={"email": {"$type": "string"}},
    )
    await _ensure_index(users_col(), [("referral_code", ASCENDING)], unique=True)
    await _ensure_index(
        users_col(),
        [("telegram_user_id", ASCENDING)],
        unique=True,
        partialFilterExpression={"telegram_user_id": {"$exists": True}},
    )

    await _ensure_index(subscriptions_col(), [("user_id", ASCENDING)])
    await _ensure_index(subscriptions_col(), [("deploy_url", ASCENDING), ("status", ASCENDING)])
    await _ensure_index(subscriptions_col(), [("status", ASCENDING), ("expires_at", ASCENDING)])

    await _ensure_index(transactions_col(), [("user_id", ASCENDING)])
    await _ensure_index(
        transactions_col(),
        [("idempotency_key", ASCENDING)],
        unique=True,
        partialFilterExpression={"idempotency_key": {"$type": "string"}},
    )

    await _ensure_index(processed_payments_col(), [("track_id", ASCENDING)], unique=True)

    await _ensure_index(oxapay_invoices_col(), [("track_id", ASCENDING)], unique=True)
    await _ensure_index(oxapay_invoices_col(), [("status", ASCENDING), ("created_at", ASCENDING)])

    await _ensure_index(telegram_login_requests_col(), [("token", ASCENDING)], unique=True)
    await _ensure_index(telegram_login_requests_col(), [("status", ASCENDING), ("expires_at", ASCENDING)])
