"""Subscription purchase (points) and cancel+refund orchestration.

Atomicity note: rather than requiring a MongoDB replica-set multi-document
transaction (which mongomock/test environments and plain standalone mongod
deployments don't support), idempotency is guaranteed via a single atomic
insert into `transactions` guarded by a unique partial index on
`idempotency_key`. That insert is the ONE guard a duplicate/retried request
must pass -- if two requests race with the same idempotency key, only one
insert can ever succeed; the loser gets a DuplicateKeyError and returns the
winner's already-recorded outcome instead of processing anything a second
time. The points balance itself is separately protected by the atomic
$gte-guarded find_one_and_update in wallet_service, so even API misuse that
skips the idempotency key still cannot cause a negative-balance double-spend.
"""

from datetime import timedelta
from app.core.timeutils import utcnow

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.constants import API_CLAIMER_CURRENCY_OPTIONS, API_CLAIMER_DROP_OPTIONS, PLANS
from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.db.mongo import subscriptions_col, transactions_col
from app.services import claimer_service, deployer_service
from app.services.wallet_service import credit_points_atomic, deduct_points_atomic


def _plan_or_404(plan_key: str) -> dict:
    plan = PLANS.get(plan_key)
    if not plan:
        raise NotFoundError(f"Unknown plan '{plan_key}'")
    return plan


def validate_claimer_settings(settings_in: dict | None) -> dict | None:
    """Validate a claimer_settings payload (currency/vault/process_all/drops)
    against the known option lists. Returns the payload unchanged if valid."""
    if not settings_in:
        return None

    currency = settings_in.get("currency")
    if currency is not None and currency not in API_CLAIMER_CURRENCY_OPTIONS:
        raise ValidationAppError(f"Invalid currency '{currency}'. Must be one of {API_CLAIMER_CURRENCY_OPTIONS}")

    drops = settings_in.get("drops")
    if drops is not None:
        invalid = [d for d in drops if d not in API_CLAIMER_DROP_OPTIONS]
        if invalid:
            raise ValidationAppError(f"Invalid drop(s) {invalid}. Must be a subset of {API_CLAIMER_DROP_OPTIONS}")

    return settings_in


async def fulfill_external_activation(sub_doc: dict) -> dict:
    """Call the external claimer activation (+ deploy for api_claimer) after
    the points/crypto payment has already been committed. Failures here do
    NOT roll back the payment -- they flag the subscription for remediation,
    since the payment was legitimately taken for a purchase attempt."""
    settings = get_settings()
    api_url = settings.API_CLAIMER_AUTH_URL if sub_doc["product_type"] == "api_claimer" else settings.CLAIMER_API_URL

    activation_ok = await claimer_service.activate(sub_doc["stake_username"], sub_doc["hours"], api_url)

    updates: dict = {"activation_failed": not activation_ok}

    if activation_ok and sub_doc["product_type"] == "api_claimer" and sub_doc.get("session_token"):
        deployer = await deployer_service.get_available_deployer()
        if deployer:
            app_name = deployer_service.generate_unique_app_name(sub_doc["stake_username"])
            ok, res = await deployer_service.deploy_container(
                sub_doc["session_token"],
                app_name,
                deployer["url"],
                deployer["token"],
                settings.API_CLAIMER_MIRROR_SITE,
                claimer_settings=sub_doc.get("claimer_settings"),
            )
            updates.update(
                {
                    "app_name": app_name,
                    "deploy_url": deployer["url"] if ok else None,
                    "deploy_status": "deployed" if ok else "failed",
                }
            )
        else:
            updates["deploy_status"] = "no_capacity"

    await subscriptions_col().update_one({"_id": sub_doc["_id"]}, {"$set": updates})
    return {**sub_doc, **updates}


async def purchase_with_points(
    user_id: ObjectId,
    product_type: str,
    plan_key: str,
    stake_username: str,
    session_token: str | None,
    idempotency_key: str,
    claimer_settings: dict | None = None,
) -> dict:
    plan = _plan_or_404(plan_key)
    claimer_settings = validate_claimer_settings(claimer_settings)
    amount = float(plan["amount"])
    now = utcnow()

    # Step 1 (the guard): claim this idempotency key. Only one caller ever wins.
    txn_doc = {
        "user_id": user_id,
        "type": "points_purchase",
        "direction": "debit",
        "amount_points": amount,
        "amount_usd": amount,
        "related_subscription_id": None,
        "related_track_id": None,
        "idempotency_key": idempotency_key,
        "status": "pending",
        "metadata": {"plan_key": plan_key, "product_type": product_type, "stake_username": stake_username},
        "created_at": now,
    }
    try:
        result = await transactions_col().insert_one(txn_doc)
        txn_doc["_id"] = result.inserted_id
    except DuplicateKeyError:
        existing = await transactions_col().find_one({"idempotency_key": idempotency_key})
        if existing and existing["status"] == "completed" and existing.get("related_subscription_id"):
            sub = await subscriptions_col().find_one({"_id": existing["related_subscription_id"]})
            return sub
        if existing and existing["status"] == "failed":
            raise ConflictError("This purchase attempt already failed; use a new Idempotency-Key to retry")
        raise ConflictError("This purchase is already being processed")

    # Step 2: atomic conditional points deduction.
    try:
        await deduct_points_atomic(user_id, amount)
    except Exception:
        await transactions_col().update_one({"_id": txn_doc["_id"]}, {"$set": {"status": "failed"}})
        raise

    # Step 3: create the subscription.
    expires_at = now + timedelta(hours=plan["hours"])
    sub_doc = {
        "user_id": user_id,
        "product_type": product_type,
        "plan_key": plan_key,
        "status": "active",
        "stake_username": stake_username,
        "session_token": session_token,
        "hours": plan["hours"],
        "amount_usd": amount,
        "started_at": now,
        "expires_at": expires_at,
        "cancelled_at": None,
        "refund_amount": None,
        "app_name": None,
        "deploy_url": None,
        "deploy_status": None,
        "activation_failed": False,
        "claimer_settings": claimer_settings,
        "created_at": now,
        "updated_at": now,
    }
    sub_result = await subscriptions_col().insert_one(sub_doc)
    sub_doc["_id"] = sub_result.inserted_id

    # Step 4: mark the ledger row completed and linked.
    await transactions_col().update_one(
        {"_id": txn_doc["_id"]},
        {"$set": {"status": "completed", "related_subscription_id": sub_doc["_id"]}},
    )

    # Step 5: external fulfillment, after the payment is already committed.
    sub_doc = await fulfill_external_activation(sub_doc)
    return sub_doc


async def list_my_subscriptions(user_id: ObjectId) -> list[dict]:
    cursor = subscriptions_col().find({"user_id": user_id}).sort("created_at", -1)
    return [doc async for doc in cursor]


async def cancel_subscription(user_id: ObjectId, subscription_id: ObjectId) -> dict:
    settings = get_settings()
    sub = await subscriptions_col().find_one({"_id": subscription_id, "user_id": user_id})
    if not sub:
        raise NotFoundError("Subscription not found")
    if sub["status"] != "active":
        raise ConflictError(f"Subscription is not active (status={sub['status']})")

    now = utcnow()
    refund_rate = (
        settings.REFUND_RATE_API_CLAIMER_PER_HOUR
        if sub["product_type"] == "api_claimer"
        else settings.REFUND_RATE_CLAIMER_PER_HOUR
    )
    remaining_hours = max(0.0, (sub["expires_at"] - now).total_seconds() / 3600.0)
    refund_amount = round(remaining_hours * refund_rate, 2)

    # The guard: only a transition FROM status="active" succeeds. A concurrent
    # duplicate cancel call will find status already flipped and get None back,
    # so it cannot credit a second refund.
    updated = await subscriptions_col().find_one_and_update(
        {"_id": subscription_id, "status": "active"},
        {"$set": {"status": "cancelled", "cancelled_at": now, "refund_amount": refund_amount, "updated_at": now}},
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise ConflictError("Subscription was already cancelled")

    if refund_amount > 0:
        await credit_points_atomic(user_id, refund_amount)
        await transactions_col().insert_one(
            {
                "user_id": user_id,
                "type": "refund",
                "direction": "credit",
                "amount_points": refund_amount,
                "amount_usd": None,
                "related_subscription_id": subscription_id,
                "related_track_id": None,
                "idempotency_key": None,
                "status": "completed",
                "metadata": {},
                "created_at": now,
            }
        )

    if sub["product_type"] == "api_claimer" and sub.get("app_name") and sub.get("deploy_url"):
        deployer = next((d for d in settings.deployers if d["url"] == sub["deploy_url"]), None)
        if deployer:
            await deployer_service.delete_container(sub["app_name"], sub["deploy_url"], deployer["token"])

    return updated


async def extend_subscription(subscription_id: ObjectId, hours: int) -> dict:
    if hours <= 0:
        raise ValidationAppError("hours must be positive")

    now = utcnow()
    sub = await subscriptions_col().find_one({"_id": subscription_id})
    if not sub:
        raise NotFoundError("Subscription not found")

    # Guarded on status="active" so this can't be applied to an already
    # cancelled/expired subscription and can't race with a concurrent cancel.
    base = sub["expires_at"] if sub["expires_at"] > now else now
    new_expiry = base + timedelta(hours=hours)

    updated = await subscriptions_col().find_one_and_update(
        {"_id": subscription_id, "status": "active"},
        {"$set": {"expires_at": new_expiry, "updated_at": now}},
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise ConflictError("Subscription is not active, cannot extend")

    settings = get_settings()
    api_url = settings.API_CLAIMER_AUTH_URL if sub["product_type"] == "api_claimer" else settings.CLAIMER_API_URL
    await claimer_service.activate(sub["stake_username"], hours, api_url)

    return updated


async def update_claimer_settings(user_id: ObjectId, subscription_id: ObjectId, settings_in: dict) -> dict:
    """Apply currency/vault/process_all/drops settings to an already-deployed
    api_claimer container (PATCH on the deployer host), then persist the new
    settings on the subscription record only if the remote apply succeeded."""
    settings_in = validate_claimer_settings(settings_in) or {}

    sub = await subscriptions_col().find_one({"_id": subscription_id, "user_id": user_id})
    if not sub:
        raise NotFoundError("Subscription not found")
    if sub["product_type"] != "api_claimer":
        raise ValidationAppError("Settings management is only available for the api_claimer product")
    if sub["status"] != "active" or not sub.get("app_name") or not sub.get("deploy_url"):
        raise ConflictError("Subscription has no active deployed container to configure")

    auth_token = deployer_service.get_deployer_auth_token(sub["deploy_url"])
    if not auth_token:
        raise ConflictError("Could not resolve the deployer for this container")

    ok, res = await deployer_service.apply_container_settings(
        sub["deploy_url"], auth_token, sub["app_name"], settings_in
    )
    if not ok:
        raise ConflictError(f"Failed to apply settings: {res.get('error', 'unknown error')}")

    merged = {**(sub.get("claimer_settings") or {}), **{k: v for k, v in settings_in.items() if v is not None}}
    updated = await subscriptions_col().find_one_and_update(
        {"_id": subscription_id},
        {"$set": {"claimer_settings": merged, "updated_at": utcnow()}},
        return_document=ReturnDocument.AFTER,
    )
    return updated


async def list_all_subscriptions(status_filter: str | None = None, product_type: str | None = None) -> list[dict]:
    query: dict = {}
    if status_filter:
        query["status"] = status_filter
    if product_type:
        query["product_type"] = product_type
    cursor = subscriptions_col().find(query).sort("created_at", -1).limit(500)
    return [doc async for doc in cursor]
