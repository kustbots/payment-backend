from bson import ObjectId
from fastapi import APIRouter, Depends

from app.constants import BULK_POINTS_PACKAGES
from app.core.errors import NotFoundError
from app.deps.auth import get_current_user
from app.models.payment import InvoiceOut
from app.models.transaction import TransactionOut
from app.models.user import UserInDB
from app.services import oxapay_service
from app.db.mongo import transactions_col

router = APIRouter(prefix="/api/wallet", tags=["wallet"])


@router.get("/balance")
async def get_balance(user: UserInDB = Depends(get_current_user)):
    return {"points": user.points}


@router.get("/bundles")
async def list_bundles():
    return [{"key": k, **v} for k, v in BULK_POINTS_PACKAGES.items()]


@router.post("/bundles/{package_key}/purchase", response_model=InvoiceOut)
async def purchase_bundle(package_key: str, user: UserInDB = Depends(get_current_user)):
    if package_key not in BULK_POINTS_PACKAGES:
        raise NotFoundError(f"Unknown points package '{package_key}'")
    invoice = await oxapay_service.start_points_bundle_invoice(ObjectId(user.id), package_key)
    return InvoiceOut(
        track_id=invoice["track_id"],
        pay_url=invoice.get("pay_url"),
        amount_usd=invoice["amount_usd"],
        purpose=invoice["purpose"],
        status=invoice["status"],
        created_at=invoice["created_at"],
    )


@router.get("/transactions", response_model=list[TransactionOut])
async def list_transactions(user: UserInDB = Depends(get_current_user)):
    cursor = transactions_col().find({"user_id": ObjectId(user.id)}).sort("created_at", -1).limit(200)
    return [TransactionOut.from_mongo(doc) async for doc in cursor]
