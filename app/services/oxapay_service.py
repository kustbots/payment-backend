"""OxaPay crypto invoice creation + credit-once payment processing.

credit_oxapay_payment() is the single choke point for crediting a paid
invoice. It is called both by the webhook route and by the fallback poller;
the unique index on processed_payments.track_id guarantees at-most-once
crediting no matter how many times or from how many places a given track_id
is reported as paid.
"""

from datetime import timedelta

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

import httpx
from app.core.timeutils import utcnow

from app.constants import BULK_POINTS_PACKAGES, PLANS
from app.core.config import get_settings
from app.core.errors import NotFoundError, UpstreamServiceError
from app.core.logging import logger
from app.db.mongo import oxapay_invoices_col, processed_payments_col, subscriptions_col, transactions_col
from app.services.referral_service import credit_referral_reward
from app.services import subscription_service
from app.services.subscription_service import fulfill_external_activation
from app.services.wallet_service import credit_points_atomic


async def create_invoice(amount: float, currency: str = "USDT", lifetime_minutes: int = 60) -> dict:
    settings = get_settings()
    url = f"{settings.OXAPAY_API_BASE}/v1/payment/invoice"
    headers = {"merchant_api_key": settings.OXAPAY_API_KEY, "Content-Type": "application/json"}
    body = {
        "amount": amount,
        "currency": currency,
        "lifetime": lifetime_minutes,
        "callbackUrl": settings.OXAPAY_CALLBACK_URL,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(url, headers=headers, json=body)
        r.raise_for_status()
        return r.json()


async def query_invoice(track_id: str) -> dict:
    settings = get_settings()
    url = f"{settings.OXAPAY_API_BASE}/merchants/inquiry"
    body = {"merchant": settings.OXAPAY_API_KEY, "trackId": track_id}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(url, headers={"Content-Type": "application/json"}, json=body)
        r.raise_for_status()
        return r.json()


def extract_invoice_fields(resp: dict) -> tuple[str, str | None]:
    """Pull (track_id, pay_url) out of OxaPay's create-invoice response.

    OxaPay's real v1 API nests the payload under "data" using snake_case keys
    (track_id, payment_url) -- not the top-level camelCase (trackId, payLink)
    this used to assume, which silently produced the literal string "None"
    for every invoice and crashed the second+ purchase attempt with a
    duplicate-key error on oxapay_invoices.track_id.
    """
    data = resp.get("data") if isinstance(resp.get("data"), dict) else {}

    track_id = (
        resp.get("track_id")
        or resp.get("trackId")
        or data.get("track_id")
        or data.get("trackId")
    )
    if not track_id:
        logger.error(f"[OXAPAY] create_invoice response missing track_id: {resp}")
        raise UpstreamServiceError("OxaPay did not return a valid invoice ID -- please try again")

    pay_url = (
        resp.get("payment_url")
        or resp.get("payLink")
        or resp.get("pay_link")
        or data.get("payment_url")
        or data.get("payLink")
        or data.get("pay_link")
    )
    return str(track_id), pay_url


def extract_invoice_status(resp_json: dict) -> str | None:
    if not resp_json:
        return None
    status = resp_json.get("status")
    if status:
        return str(status).lower()
    data = resp_json.get("data") or resp_json.get("result") or resp_json.get("response")
    if isinstance(data, dict):
        s = data.get("status") or data.get("payment_status") or data.get("state")
        if s:
            return str(s).lower()
    if isinstance(resp_json.get("data"), list) and resp_json["data"]:
        el = resp_json["data"][0]
        if isinstance(el, dict) and el.get("status"):
            return str(el["status"]).lower()
    return None


async def start_plan_purchase_invoice(
    user_id: ObjectId,
    product_type: str,
    plan_key: str,
    stake_username: str,
    session_token: str | None,
    claimer_settings: dict | None = None,
) -> dict:
    plan = PLANS.get(plan_key)
    if not plan:
        raise NotFoundError(f"Unknown plan '{plan_key}'")
    subscription_service.require_session_token_for_api_claimer(product_type, session_token)
    claimer_settings = subscription_service.validate_claimer_settings(claimer_settings)

    resp = await create_invoice(plan["amount"])
    track_id, pay_url = extract_invoice_fields(resp)

    now = utcnow()
    invoice_doc = {
        "user_id": user_id,
        "track_id": track_id,
        "purpose": "plan_purchase",
        "purpose_ref": {
            "product_type": product_type,
            "plan_key": plan_key,
            "stake_username": stake_username,
            "session_token": session_token,
            "hours": plan["hours"],
            "claimer_settings": claimer_settings,
        },
        "amount_usd": plan["amount"],
        "pay_url": pay_url,
        "status": "pending",
        "created_at": now,
        "updated_at": now,
    }
    await oxapay_invoices_col().insert_one(invoice_doc)
    return invoice_doc


async def start_points_bundle_invoice(user_id: ObjectId, package_key: str) -> dict:
    package = BULK_POINTS_PACKAGES.get(package_key)
    if not package:
        raise NotFoundError(f"Unknown points package '{package_key}'")

    resp = await create_invoice(package["amount"])
    track_id, pay_url = extract_invoice_fields(resp)

    now = utcnow()
    invoice_doc = {
        "user_id": user_id,
        "track_id": track_id,
        "purpose": "points_bundle",
        "purpose_ref": {"package_key": package_key, "points": package["points"]},
        "amount_usd": package["amount"],
        "pay_url": pay_url,
        "status": "pending",
        "created_at": now,
        "updated_at": now,
    }
    await oxapay_invoices_col().insert_one(invoice_doc)
    return invoice_doc


async def credit_oxapay_payment(track_id: str) -> None:
    invoice = await oxapay_invoices_col().find_one({"track_id": track_id})
    if not invoice:
        logger.warning(f"credit_oxapay_payment: unknown track_id {track_id}")
        return
    if invoice["status"] == "paid":
        return  # already fulfilled locally, nothing to do

    now = utcnow()

    # Atomic "claim" step -- the unique index is the real guard.
    try:
        await processed_payments_col().insert_one(
            {
                "track_id": track_id,
                "status": "credited",
                "purpose": invoice["purpose"],
                "user_id": invoice["user_id"],
                "amount_usd": invoice["amount_usd"],
                "created_at": now,
            }
        )
    except DuplicateKeyError:
        return  # already credited by a prior webhook/poll firing -- safe no-op

    if invoice["purpose"] == "points_bundle":
        points = invoice["purpose_ref"]["points"]
        await credit_points_atomic(invoice["user_id"], points)
        await transactions_col().insert_one(
            {
                "user_id": invoice["user_id"],
                "type": "bulk_points_credit",
                "direction": "credit",
                "amount_points": points,
                "amount_usd": invoice["amount_usd"],
                "related_subscription_id": None,
                "related_track_id": track_id,
                "idempotency_key": None,
                "status": "completed",
                "metadata": invoice["purpose_ref"],
                "created_at": now,
            }
        )
    else:  # plan_purchase
        ref = invoice["purpose_ref"]
        expires_at = now + timedelta(hours=ref["hours"])
        sub_doc = {
            "user_id": invoice["user_id"],
            "product_type": ref["product_type"],
            "plan_key": ref["plan_key"],
            "status": "active",
            "stake_username": ref["stake_username"],
            "session_token": ref.get("session_token"),
            "hours": ref["hours"],
            "amount_usd": invoice["amount_usd"],
            "started_at": now,
            "expires_at": expires_at,
            "cancelled_at": None,
            "refund_amount": None,
            "app_name": None,
            "deploy_url": None,
            "deploy_status": None,
            "deploy_progress": None,
            "deploy_message": None,
            "activation_failed": False,
            "claimer_settings": ref.get("claimer_settings"),
            "created_at": now,
            "updated_at": now,
        }
        result = await subscriptions_col().insert_one(sub_doc)
        sub_doc["_id"] = result.inserted_id
        await transactions_col().insert_one(
            {
                "user_id": invoice["user_id"],
                "type": "crypto_invoice",
                "direction": "debit",
                "amount_points": 0.0,
                "amount_usd": invoice["amount_usd"],
                "related_subscription_id": sub_doc["_id"],
                "related_track_id": track_id,
                "idempotency_key": None,
                "status": "completed",
                "metadata": ref,
                "created_at": now,
            }
        )
        await fulfill_external_activation(sub_doc)
        # Referral reward only fires for crypto purchases, per the preserved business rule.
        await credit_referral_reward(invoice["user_id"], invoice["amount_usd"])

    await oxapay_invoices_col().update_one({"track_id": track_id}, {"$set": {"status": "paid", "updated_at": now}})
