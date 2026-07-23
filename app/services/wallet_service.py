"""Atomic points balance primitives.

Every points deduction in this codebase MUST go through deduct_points_atomic()
(a single find_one_and_update with a $gte guard), never a separate
"read balance, check in Python, then update" sequence -- that pattern is the
TOCTOU double-spend bug this backend was built to eliminate.
"""

from app.core.timeutils import utcnow

from bson import ObjectId
from pymongo import ReturnDocument

from app.core.errors import InsufficientPointsError, UserNotFoundError
from app.db.mongo import transactions_col, users_col


async def deduct_points_atomic(user_id: ObjectId, amount: float, *, session=None) -> dict:
    """Atomically deduct `amount` points iff the user currently has >= amount.

    Returns the updated user document. Raises InsufficientPointsError or
    UserNotFoundError if the guarded update did not match any document.
    """
    if amount <= 0:
        raise ValueError("amount must be positive")

    updated = await users_col().find_one_and_update(
        {"_id": user_id, "points": {"$gte": amount}},
        {"$inc": {"points": -amount}},
        return_document=ReturnDocument.AFTER,
        session=session,
    )
    if updated is not None:
        return updated

    # Disambiguate the failure reason with a read-only lookup (never used for the
    # deduction decision itself).
    existing = await users_col().find_one({"_id": user_id}, session=session)
    if existing is None:
        raise UserNotFoundError()
    raise InsufficientPointsError(balance=existing.get("points", 0.0), required=amount)


async def credit_points_atomic(user_id: ObjectId, amount: float, *, session=None) -> dict:
    if amount <= 0:
        raise ValueError("amount must be positive")

    updated = await users_col().find_one_and_update(
        {"_id": user_id},
        {"$inc": {"points": amount}},
        return_document=ReturnDocument.AFTER,
        session=session,
    )
    if updated is None:
        raise UserNotFoundError()
    return updated


async def get_balance(user_id: ObjectId) -> float:
    doc = await users_col().find_one({"_id": user_id}, {"points": 1})
    if doc is None:
        raise UserNotFoundError()
    return doc.get("points", 0.0)


async def admin_grant_points(user_id: ObjectId, amount: float) -> dict:
    if amount == 0:
        raise ValueError("amount must be non-zero")
    updated = await credit_points_atomic(user_id, amount) if amount > 0 else await deduct_points_atomic(user_id, -amount)
    await transactions_col().insert_one(
        {
            "user_id": user_id,
            "type": "admin_grant",
            "direction": "credit" if amount > 0 else "debit",
            "amount_points": abs(amount),
            "amount_usd": None,
            "related_subscription_id": None,
            "related_track_id": None,
            "idempotency_key": None,
            "status": "completed",
            "metadata": {},
            "created_at": utcnow(),
        }
    )
    return updated
