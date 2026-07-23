from datetime import datetime

from pydantic import BaseModel


class InvoiceOut(BaseModel):
    track_id: str
    pay_url: str | None = None
    amount_usd: float
    purpose: str
    status: str
    created_at: datetime


class OxapayWebhookPayload(BaseModel):
    track_id: str
    status: str
    amount: float | None = None
    order_id: str | None = None
