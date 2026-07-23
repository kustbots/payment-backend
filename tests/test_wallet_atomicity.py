import asyncio

import pytest
from bson import ObjectId

from app.core.errors import InsufficientPointsError
from app.db.mongo import users_col
from app.services.wallet_service import deduct_points_atomic


async def _make_user(points: float) -> ObjectId:
    result = await users_col().insert_one({"email": "a@test.com", "points": points})
    return result.inserted_id


@pytest.mark.asyncio
async def test_deduct_succeeds_when_sufficient():
    user_id = await _make_user(10.0)
    await deduct_points_atomic(user_id, 10.0)
    doc = await users_col().find_one({"_id": user_id})
    assert doc["points"] == 0.0


@pytest.mark.asyncio
async def test_deduct_raises_when_insufficient():
    user_id = await _make_user(5.0)
    with pytest.raises(InsufficientPointsError):
        await deduct_points_atomic(user_id, 10.0)
    doc = await users_col().find_one({"_id": user_id})
    assert doc["points"] == 5.0  # untouched


@pytest.mark.asyncio
async def test_concurrent_deduction_cannot_double_spend():
    """Balance=10, price=10: firing two concurrent deductions must let exactly
    one succeed and the other fail with InsufficientPointsError -- this is
    the exact race the legacy bot's pay_points_handler was vulnerable to."""
    user_id = await _make_user(10.0)

    results = await asyncio.gather(
        deduct_points_atomic(user_id, 10.0),
        deduct_points_atomic(user_id, 10.0),
        return_exceptions=True,
    )

    successes = [r for r in results if not isinstance(r, Exception)]
    failures = [r for r in results if isinstance(r, InsufficientPointsError)]

    assert len(successes) == 1
    assert len(failures) == 1

    doc = await users_col().find_one({"_id": user_id})
    assert doc["points"] == 0.0  # never went negative, never double-spent
