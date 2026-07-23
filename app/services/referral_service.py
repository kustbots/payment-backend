import random
import string
from app.core.timeutils import utcnow

from bson import ObjectId

from app.constants import REFERRAL_REWARD_RATE
from app.core.logging import logger
from app.db.mongo import transactions_col, users_col
from app.services.wallet_service import credit_points_atomic


def generate_referral_code() -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


async def resolve_referrer(referral_code: str | None) -> ObjectId | None:
    if not referral_code:
        return None
    referrer = await users_col().find_one({"referral_code": referral_code})
    if not referrer:
        return None
    return referrer["_id"]


async def credit_referral_reward(referred_user_id: ObjectId, amount_usd: float, *, session=None) -> None:
    """Credit 10% of a CRYPTO purchase to the referrer, if any.

    Only ever called from the crypto payment-credit path -- points-paid
    purchases intentionally do not trigger a referral reward, matching the
    legacy bot's business rule.
    """
    user = await users_col().find_one({"_id": referred_user_id}, session=session)
    if not user or not user.get("referrer_id"):
        return

    referrer_id = user["referrer_id"]
    reward = round(amount_usd * REFERRAL_REWARD_RATE, 2)
    if reward <= 0:
        return

    try:
        await credit_points_atomic(referrer_id, reward, session=session)
        await transactions_col().insert_one(
            {
                "user_id": referrer_id,
                "type": "referral_credit",
                "direction": "credit",
                "amount_points": reward,
                "amount_usd": amount_usd,
                "related_subscription_id": None,
                "related_track_id": None,
                "idempotency_key": None,
                "status": "completed",
                "metadata": {"referred_user_id": str(referred_user_id)},
                "created_at": utcnow(),
            },
            session=session,
        )
    except Exception as e:
        logger.exception(f"Failed to credit referral reward to {referrer_id}: {e}")
