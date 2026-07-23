import hashlib
import hmac

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.deps.auth import get_current_admin, get_current_user
from app.db.mongo import oxapay_invoices_col
from app.models.user import UserInDB
from app.services import oxapay_service

router = APIRouter(prefix="/api/payments", tags=["payments"])


def _verify_oxapay_signature(raw_body: bytes, signature: str | None) -> bool:
    settings = get_settings()
    if not signature or not settings.OXAPAY_API_KEY:
        return False
    expected = hmac.new(settings.OXAPAY_API_KEY.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/oxapay/webhook")
async def oxapay_webhook(request: Request):
    raw_body = await request.body()
    signature = request.headers.get("HMAC") or request.headers.get("hmac")

    if not _verify_oxapay_signature(raw_body, signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature")

    payload = await request.json()
    track_id = str(payload.get("trackId") or payload.get("track_id") or "")
    payment_status = str(payload.get("status", "")).lower()

    if track_id and payment_status == "paid":
        await oxapay_service.credit_oxapay_payment(track_id)

    return {"ok": True}


@router.get("/invoices/{track_id}")
async def get_invoice(track_id: str, user: UserInDB = Depends(get_current_user)):
    invoice = await oxapay_invoices_col().find_one({"track_id": track_id})
    if not invoice or str(invoice["user_id"]) != user.id:
        raise NotFoundError("Invoice not found")
    return {
        "track_id": invoice["track_id"],
        "purpose": invoice["purpose"],
        "amount_usd": invoice["amount_usd"],
        "status": invoice["status"],
        "created_at": invoice["created_at"],
    }


def _register_dev_routes(router: APIRouter) -> None:
    settings = get_settings()
    if settings.is_production:
        return

    @router.post("/dev/mark-paid/{track_id}")
    async def dev_mark_paid(track_id: str, _admin: UserInDB = Depends(get_current_admin)):
        """Non-production only: simulate an OxaPay webhook for local smoke testing."""
        await oxapay_service.credit_oxapay_payment(track_id)
        return {"ok": True}


_register_dev_routes(router)
