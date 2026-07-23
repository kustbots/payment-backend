from bson import ObjectId
from fastapi import APIRouter, Depends

from app.db.mongo import users_col
from app.deps.auth import get_current_user
from app.models.user import UserInDB

router = APIRouter(prefix="/api/referrals", tags=["referrals"])


@router.get("/me")
async def my_referral_info(user: UserInDB = Depends(get_current_user)):
    referred_count = await users_col().count_documents({"referrer_id": ObjectId(user.id)})
    return {"referral_code": user.referral_code, "referred_count": referred_count}
