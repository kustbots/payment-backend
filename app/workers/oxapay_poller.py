"""Fallback poller for OxaPay invoices, in case the push webhook never arrives.

Shares credit_oxapay_payment() with the webhook route -- the unique index on
processed_payments.track_id makes it safe for both to fire for the same
invoice without double-crediting.
"""

import asyncio
from datetime import timedelta
from app.core.timeutils import utcnow

from app.core.config import get_settings
from app.core.logging import logger
from app.db.mongo import oxapay_invoices_col
from app.services.oxapay_service import extract_invoice_status, credit_oxapay_payment, query_invoice


async def _poll_once() -> None:
    settings = get_settings()
    cutoff = utcnow() - timedelta(seconds=settings.PAYMENT_TIMEOUT_SECONDS)

    cursor = oxapay_invoices_col().find({"status": "pending", "created_at": {"$gt": cutoff}})
    async for invoice in cursor:
        try:
            data = await query_invoice(invoice["track_id"])
            status = extract_invoice_status(data)
            if status == "paid":
                await credit_oxapay_payment(invoice["track_id"])
            elif status in ("expired", "cancelled", "cancel", "failed"):
                await oxapay_invoices_col().update_one(
                    {"track_id": invoice["track_id"]}, {"$set": {"status": "expired"}}
                )
        except Exception as e:
            logger.exception(f"[OXAPAY_POLLER] Error polling invoice {invoice['track_id']}: {e}")

    # Mark anything past the timeout window as expired so it stops being polled.
    await oxapay_invoices_col().update_many(
        {"status": "pending", "created_at": {"$lte": cutoff}}, {"$set": {"status": "expired"}}
    )


async def run_forever() -> None:
    settings = get_settings()
    logger.info("OxaPay fallback poller started")
    while True:
        try:
            await _poll_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception(f"[OXAPAY_POLLER] top-level error: {e}")
        await asyncio.sleep(settings.POLL_INTERVAL_SECONDS)
