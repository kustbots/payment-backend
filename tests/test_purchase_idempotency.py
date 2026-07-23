import asyncio

import pytest
from bson import ObjectId

from app.core.errors import InsufficientPointsError
from app.db.mongo import subscriptions_col, users_col
from app.services import subscription_service


async def _make_user(points: float) -> ObjectId:
    result = await users_col().insert_one({"email": "buyer@test.com", "points": points})
    return result.inserted_id


@pytest.mark.asyncio
async def test_purchase_with_points_deducts_and_creates_subscription():
    user_id = await _make_user(6.0)
    sub = await subscription_service.purchase_with_points(
        user_id=user_id,
        product_type="code_claimer",
        plan_key="2d",
        stake_username="tester",
        session_token=None,
        idempotency_key="key-1",
    )
    assert sub["status"] == "active"
    user = await users_col().find_one({"_id": user_id})
    assert user["points"] == 0.0


@pytest.mark.asyncio
async def test_retry_with_same_idempotency_key_does_not_double_deduct():
    user_id = await _make_user(6.0)
    kwargs = dict(
        user_id=user_id,
        product_type="code_claimer",
        plan_key="2d",
        stake_username="tester",
        session_token=None,
        idempotency_key="key-retry",
    )
    sub1 = await subscription_service.purchase_with_points(**kwargs)
    sub2 = await subscription_service.purchase_with_points(**kwargs)

    assert str(sub1["_id"]) == str(sub2["_id"])
    user = await users_col().find_one({"_id": user_id})
    assert user["points"] == 0.0  # only deducted once despite two calls

    count = await subscriptions_col().count_documents({"user_id": user_id})
    assert count == 1


@pytest.mark.asyncio
async def test_concurrent_identical_purchase_only_succeeds_once():
    user_id = await _make_user(6.0)
    kwargs = dict(
        user_id=user_id,
        product_type="code_claimer",
        plan_key="2d",
        stake_username="tester",
        session_token=None,
        idempotency_key="key-concurrent",
    )
    await asyncio.gather(
        subscription_service.purchase_with_points(**kwargs),
        subscription_service.purchase_with_points(**kwargs),
        return_exceptions=True,
    )
    # Both calls should resolve without raising (second is a no-op returning
    # the first's subscription) OR the loser could get a Conflict if it lands
    # mid-processing; either way points must only be spent once.
    user = await users_col().find_one({"_id": user_id})
    assert user["points"] == 0.0

    count = await subscriptions_col().count_documents({"user_id": user_id})
    assert count == 1


@pytest.mark.asyncio
async def test_insufficient_points_rejected():
    user_id = await _make_user(1.0)
    with pytest.raises(InsufficientPointsError):
        await subscription_service.purchase_with_points(
            user_id=user_id,
            product_type="code_claimer",
            plan_key="2d",
            stake_username="tester",
            session_token=None,
            idempotency_key="key-poor",
        )
    user = await users_col().find_one({"_id": user_id})
    assert user["points"] == 1.0
