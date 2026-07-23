import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId

from app.core.errors import ConflictError
from app.db.mongo import subscriptions_col, users_col
from app.services import subscription_service


async def _make_active_subscription(user_id: ObjectId, hours_remaining: float) -> ObjectId:
    now = datetime.now(timezone.utc)
    result = await subscriptions_col().insert_one(
        {
            "user_id": user_id,
            "product_type": "code_claimer",
            "plan_key": "7d",
            "status": "active",
            "stake_username": "tester",
            "hours": 168,
            "amount_usd": 15.0,
            "started_at": now,
            "expires_at": now + timedelta(hours=hours_remaining),
            "cancelled_at": None,
            "refund_amount": None,
            "app_name": None,
            "deploy_url": None,
            "deploy_status": None,
            "activation_failed": False,
            "created_at": now,
            "updated_at": now,
        }
    )
    return result.inserted_id


@pytest.mark.asyncio
async def test_cancel_transitions_status_once():
    user_result = await users_col().insert_one({"email": "cancel@test.com", "points": 0.0})
    user_id = user_result.inserted_id
    sub_id = await _make_active_subscription(user_id, 24)

    updated = await subscription_service.cancel_subscription(user_id, sub_id)
    assert updated["status"] == "cancelled"


@pytest.mark.asyncio
async def test_double_cancel_does_not_double_refund():
    from app.core.config import get_settings

    settings = get_settings()
    original_rate = settings.REFUND_RATE_CLAIMER_PER_HOUR
    settings.REFUND_RATE_CLAIMER_PER_HOUR = 1.0  # force a non-zero refund rate for this test

    user_result = await users_col().insert_one({"email": "cancel2@test.com", "points": 0.0})
    user_id = user_result.inserted_id
    sub_id = await _make_active_subscription(user_id, 10)

    await subscription_service.cancel_subscription(user_id, sub_id)

    with pytest.raises(ConflictError):
        await subscription_service.cancel_subscription(user_id, sub_id)

    user = await users_col().find_one({"_id": user_id})
    # Refunded once (~10 points for 10 remaining hours at rate 1.0/hr), not twice.
    assert 9.0 <= user["points"] <= 10.0

    settings.REFUND_RATE_CLAIMER_PER_HOUR = original_rate


@pytest.mark.asyncio
async def test_concurrent_cancel_only_refunds_once():
    from app.core.config import get_settings

    settings = get_settings()
    original_rate = settings.REFUND_RATE_CLAIMER_PER_HOUR
    settings.REFUND_RATE_CLAIMER_PER_HOUR = 1.0

    user_result = await users_col().insert_one({"email": "cancel3@test.com", "points": 0.0})
    user_id = user_result.inserted_id
    sub_id = await _make_active_subscription(user_id, 10)

    await asyncio.gather(
        subscription_service.cancel_subscription(user_id, sub_id),
        subscription_service.cancel_subscription(user_id, sub_id),
        return_exceptions=True,
    )

    user = await users_col().find_one({"_id": user_id})
    assert 9.0 <= user["points"] <= 10.0  # exactly one refund credited

    settings.REFUND_RATE_CLAIMER_PER_HOUR = original_rate
