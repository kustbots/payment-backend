import asyncio

import pytest
from bson import ObjectId

from app.core.errors import ValidationAppError
from app.db.mongo import subscriptions_col, users_col
from app.services import deployer_service, subscription_service
from app.services.subscription_service import _estimate_deploy_progress, require_session_token_for_api_claimer


async def _make_user(points: float) -> ObjectId:
    result = await users_col().insert_one({"email": "deploytest@test.com", "points": points})
    return result.inserted_id


def test_require_session_token_raises_for_api_claimer_without_token():
    with pytest.raises(ValidationAppError):
        require_session_token_for_api_claimer("api_claimer", None)
    with pytest.raises(ValidationAppError):
        require_session_token_for_api_claimer("api_claimer", "")


def test_require_session_token_allows_code_claimer_without_token():
    require_session_token_for_api_claimer("code_claimer", None)  # should not raise


def test_require_session_token_allows_api_claimer_with_token():
    require_session_token_for_api_claimer("api_claimer", "sometoken")  # should not raise


@pytest.mark.asyncio
async def test_purchase_with_points_rejects_api_claimer_without_session_token():
    user_id = await _make_user(100.0)
    with pytest.raises(ValidationAppError):
        await subscription_service.purchase_with_points(
            user_id=user_id,
            product_type="api_claimer",
            plan_key="2d",
            stake_username="tester",
            session_token=None,
            idempotency_key="no-token-key",
        )


def test_estimate_deploy_progress_uses_numeric_field_when_present():
    assert _estimate_deploy_progress({"progress": 42}) == 42
    assert _estimate_deploy_progress({"percent": 150}) == 100  # clamped
    assert _estimate_deploy_progress({"percentage": -5}) == 0  # clamped


def test_estimate_deploy_progress_falls_back_to_stage_name():
    assert _estimate_deploy_progress({"status": "building"}) == 40
    assert _estimate_deploy_progress({"status": "completed"}) == 100
    assert _estimate_deploy_progress({"status": "some_unknown_stage"}) == 50


@pytest.mark.asyncio
async def test_purchase_with_points_kicks_off_background_deploy_with_progress(monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    original = settings.API_CLAIMER_DEPLOYERS
    settings.API_CLAIMER_DEPLOYERS = (
        '[{"deploy_id": 1, "url": "https://deployer1.example.com", "token": "tok1", "limit": 100}]'
    )

    async def fake_activate(username, hours, api_url):
        return True

    async def fake_deploy_container(session_token, app_name, deploy_url, auth_token, mirror_site, **kwargs):
        on_update = kwargs.get("on_update")
        if on_update:
            await on_update({"status": "building"})
            await on_update({"status": "completed"})
        return True, {"status": "completed"}

    monkeypatch.setattr(subscription_service.claimer_service, "activate", fake_activate)
    monkeypatch.setattr(deployer_service, "deploy_container", fake_deploy_container)

    user_id = await _make_user(100.0)
    sub = await subscription_service.purchase_with_points(
        user_id=user_id,
        product_type="api_claimer",
        plan_key="2d",
        stake_username="tester",
        session_token="realtoken",
        idempotency_key="deploy-progress-key",
    )
    assert sub["deploy_status"] == "deploying"
    assert sub["deploy_progress"] == 0

    # Let the background task run to completion.
    await asyncio.sleep(0.05)

    updated = await subscriptions_col().find_one({"_id": sub["_id"]})
    assert updated["deploy_status"] == "deployed"
    assert updated["deploy_progress"] == 100

    settings.API_CLAIMER_DEPLOYERS = original
