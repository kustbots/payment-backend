from bson import ObjectId
from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends

from app.core.errors import NotFoundError, ValidationAppError
from app.db.mongo import users_col
from app.deps.auth import get_current_admin
from app.models.subscription import SubscriptionOut
from app.models.user import UserInDB, UserOut
from app.services import subscription_service, wallet_service

router = APIRouter(prefix="/api/admin", tags=["admin"])


class GrantPointsRequest(BaseModel):
    amount: float = Field(..., description="Positive to grant, negative to deduct")


class ExtendSubscriptionRequest(BaseModel):
    hours: int = Field(gt=0, le=8760)  # capped at 1 year, defense in depth


@router.post("/users/{user_id}/grant-points", response_model=UserOut)
async def grant_points(user_id: str, payload: GrantPointsRequest, _admin: UserInDB = Depends(get_current_admin)):
    if not ObjectId.is_valid(user_id):
        raise ValidationAppError("Invalid user id")
    if payload.amount == 0:
        raise ValidationAppError("amount must be non-zero")
    await wallet_service.admin_grant_points(ObjectId(user_id), payload.amount)
    doc = await users_col().find_one({"_id": ObjectId(user_id)})
    if not doc:
        raise NotFoundError("User not found")
    return UserInDB.from_mongo(doc).to_out()


@router.get("/users/{user_id}", response_model=UserOut)
async def get_user(user_id: str, _admin: UserInDB = Depends(get_current_admin)):
    if not ObjectId.is_valid(user_id):
        raise ValidationAppError("Invalid user id")
    doc = await users_col().find_one({"_id": ObjectId(user_id)})
    if not doc:
        raise NotFoundError("User not found")
    return UserInDB.from_mongo(doc).to_out()


@router.post("/subscriptions/{subscription_id}/extend", response_model=SubscriptionOut)
async def extend_subscription(
    subscription_id: str, payload: ExtendSubscriptionRequest, _admin: UserInDB = Depends(get_current_admin)
):
    if not ObjectId.is_valid(subscription_id):
        raise ValidationAppError("Invalid subscription id")
    sub = await subscription_service.extend_subscription(ObjectId(subscription_id), payload.hours)
    return SubscriptionOut.from_mongo(sub)


@router.get("/subscriptions", response_model=list[SubscriptionOut])
async def list_subscriptions(
    status: str | None = None, product_type: str | None = None, _admin: UserInDB = Depends(get_current_admin)
):
    subs = await subscription_service.list_all_subscriptions(status, product_type)
    return [SubscriptionOut.from_mongo(s) for s in subs]
