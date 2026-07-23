import pytest
from bson import ObjectId

from app.core.errors import ConflictError, ValidationAppError
from app.core.timeutils import utcnow
from app.db.mongo import subscriptions_col, users_col
from app.services import deployer_service, subscription_service


def test_validate_claimer_settings_rejects_bad_currency():
    with pytest.raises(ValidationAppError):
        subscription_service.validate_claimer_settings({"currency": "not-a-real-coin"})


def test_validate_claimer_settings_rejects_bad_drop():
    with pytest.raises(ValidationAppError):
        subscription_service.validate_claimer_settings({"drops": ["NotARealDrop"]})


def test_validate_claimer_settings_accepts_valid_payload():
    payload = {"currency": "usdt", "vault": True, "process_all": False, "drops": ["Daily1", "HighRollers"]}
    assert subscription_service.validate_claimer_settings(payload) == payload


def test_validate_claimer_settings_none_passthrough():
    assert subscription_service.validate_claimer_settings(None) is None


@pytest.mark.asyncio
async def test_purchase_with_points_stores_claimer_settings():
    user_result = await users_col().insert_one({"email": "settings@test.com", "points": 6.0})
    user_id = user_result.inserted_id

    sub = await subscription_service.purchase_with_points(
        user_id=user_id,
        product_type="code_claimer",
        plan_key="2d",
        stake_username="settingsuser",
        session_token=None,
        idempotency_key="settings-key-1",
        claimer_settings={"currency": "btc", "vault": True, "process_all": None, "drops": ["Daily1"]},
    )
    assert sub["claimer_settings"] == {"currency": "btc", "vault": True, "process_all": None, "drops": ["Daily1"]}


async def _make_deployed_subscription(user_id: ObjectId, **overrides) -> ObjectId:
    now = utcnow()
    doc = {
        "user_id": user_id,
        "product_type": "api_claimer",
        "plan_key": "2d",
        "status": "active",
        "stake_username": "tester",
        "hours": 48,
        "amount_usd": 6.0,
        "started_at": now,
        "expires_at": now,
        "cancelled_at": None,
        "refund_amount": None,
        "app_name": "api-cl-tester-abcd",
        "deploy_url": "https://deployer1.example.com",
        "deploy_status": "deployed",
        "activation_failed": False,
        "claimer_settings": {"currency": "usdt", "vault": None, "process_all": None, "drops": None},
        "created_at": now,
        "updated_at": now,
    }
    doc.update(overrides)
    result = await subscriptions_col().insert_one(doc)
    return result.inserted_id


@pytest.mark.asyncio
async def test_update_claimer_settings_applies_and_merges(monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    original = settings.API_CLAIMER_DEPLOYERS
    settings.API_CLAIMER_DEPLOYERS = (
        '[{"deploy_id": 1, "url": "https://deployer1.example.com", "token": "tok1", "limit": 100}]'
    )

    async def fake_apply(deploy_url, auth_token, app_name, settings_payload):
        assert deploy_url == "https://deployer1.example.com"
        assert auth_token == "tok1"
        return True, {"status": "ok"}

    monkeypatch.setattr(deployer_service, "apply_container_settings", fake_apply)

    user_result = await users_col().insert_one({"email": "manage@test.com", "points": 0.0})
    user_id = user_result.inserted_id
    sub_id = await _make_deployed_subscription(user_id)

    updated = await subscription_service.update_claimer_settings(
        user_id, sub_id, {"currency": "eth", "vault": True, "process_all": None, "drops": None}
    )
    assert updated["claimer_settings"]["currency"] == "eth"
    assert updated["claimer_settings"]["vault"] is True

    settings.API_CLAIMER_DEPLOYERS = original


@pytest.mark.asyncio
async def test_update_claimer_settings_rejects_non_api_claimer():
    user_result = await users_col().insert_one({"email": "wrongtype@test.com", "points": 0.0})
    user_id = user_result.inserted_id
    sub_id = await _make_deployed_subscription(user_id, product_type="code_claimer")

    with pytest.raises(ValidationAppError):
        await subscription_service.update_claimer_settings(user_id, sub_id, {"currency": "usdt"})


@pytest.mark.asyncio
async def test_update_claimer_settings_rejects_no_deployed_container():
    user_result = await users_col().insert_one({"email": "nocontainer@test.com", "points": 0.0})
    user_id = user_result.inserted_id
    sub_id = await _make_deployed_subscription(user_id, app_name=None, deploy_url=None)

    with pytest.raises(ConflictError):
        await subscription_service.update_claimer_settings(user_id, sub_id, {"currency": "usdt"})


@pytest.mark.asyncio
async def test_update_claimer_settings_surfaces_remote_failure(monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    original = settings.API_CLAIMER_DEPLOYERS
    settings.API_CLAIMER_DEPLOYERS = (
        '[{"deploy_id": 1, "url": "https://deployer1.example.com", "token": "tok1", "limit": 100}]'
    )

    async def fake_apply_fail(deploy_url, auth_token, app_name, settings_payload):
        return False, {"error": "container unreachable"}

    monkeypatch.setattr(deployer_service, "apply_container_settings", fake_apply_fail)

    user_result = await users_col().insert_one({"email": "failapply@test.com", "points": 0.0})
    user_id = user_result.inserted_id
    sub_id = await _make_deployed_subscription(user_id)

    with pytest.raises(ConflictError):
        await subscription_service.update_claimer_settings(user_id, sub_id, {"currency": "usdt"})

    settings.API_CLAIMER_DEPLOYERS = original
