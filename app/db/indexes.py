from pymongo import ASCENDING

from app.db.mongo import (
    oxapay_invoices_col,
    processed_payments_col,
    subscriptions_col,
    transactions_col,
    users_col,
)


async def create_indexes() -> None:
    await users_col().create_index([("email", ASCENDING)], unique=True)
    await users_col().create_index([("referral_code", ASCENDING)], unique=True)

    await subscriptions_col().create_index([("user_id", ASCENDING)])
    await subscriptions_col().create_index([("deploy_url", ASCENDING), ("status", ASCENDING)])
    await subscriptions_col().create_index([("status", ASCENDING), ("expires_at", ASCENDING)])

    await transactions_col().create_index([("user_id", ASCENDING)])
    await transactions_col().create_index(
        [("idempotency_key", ASCENDING)],
        unique=True,
        partialFilterExpression={"idempotency_key": {"$type": "string"}},
    )

    await processed_payments_col().create_index([("track_id", ASCENDING)], unique=True)

    await oxapay_invoices_col().create_index([("track_id", ASCENDING)], unique=True)
    await oxapay_invoices_col().create_index([("status", ASCENDING), ("created_at", ASCENDING)])
