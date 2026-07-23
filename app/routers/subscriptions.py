from bson import ObjectId
from fastapi import APIRouter, Depends, Header

from app.constants import PLANS
from app.core.errors import ValidationAppError
from app.deps.auth import get_current_user
from app.models.payment import InvoiceOut
from app.models.subscription import (
    PlanOut,
    PurchaseWithCryptoRequest,
    PurchaseWithPointsRequest,
    SubscriptionOut,
)
from app.models.user import UserInDB
from app.services import oxapay_service, subscription_service

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])


@router.get("/plans", response_model=list[PlanOut])
async def list_plans():
    return [PlanOut(key=k, **v) for k, v in PLANS.items()]


@router.post("/purchase/points", response_model=SubscriptionOut)
async def purchase_with_points(
    payload: PurchaseWithPointsRequest,
    user: UserInDB = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    if not idempotency_key:
        raise ValidationAppError("Idempotency-Key header is required")

    sub = await subscription_service.purchase_with_points(
        user_id=ObjectId(user.id),
        product_type=payload.product_type,
        plan_key=payload.plan_key,
        stake_username=payload.stake_username,
        session_token=payload.session_token,
        idempotency_key=idempotency_key,
    )
    return SubscriptionOut.from_mongo(sub)


@router.post("/purchase/crypto", response_model=InvoiceOut)
async def purchase_with_crypto(payload: PurchaseWithCryptoRequest, user: UserInDB = Depends(get_current_user)):
    invoice = await oxapay_service.start_plan_purchase_invoice(
        user_id=ObjectId(user.id),
        product_type=payload.product_type,
        plan_key=payload.plan_key,
        stake_username=payload.stake_username,
        session_token=payload.session_token,
    )
    return InvoiceOut(
        track_id=invoice["track_id"],
        pay_url=invoice.get("pay_url"),
        amount_usd=invoice["amount_usd"],
        purpose=invoice["purpose"],
        status=invoice["status"],
        created_at=invoice["created_at"],
    )


@router.get("/me", response_model=list[SubscriptionOut])
async def list_my_subscriptions(user: UserInDB = Depends(get_current_user)):
    subs = await subscription_service.list_my_subscriptions(ObjectId(user.id))
    return [SubscriptionOut.from_mongo(s) for s in subs]


@router.post("/{subscription_id}/cancel", response_model=SubscriptionOut)
async def cancel_subscription(subscription_id: str, user: UserInDB = Depends(get_current_user)):
    if not ObjectId.is_valid(subscription_id):
        raise ValidationAppError("Invalid subscription id")
    sub = await subscription_service.cancel_subscription(ObjectId(user.id), ObjectId(subscription_id))
    return SubscriptionOut.from_mongo(sub)
