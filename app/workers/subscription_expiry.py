"""Reaps subscriptions once they pass their expiry: tears down the api_claimer
container (if any) on the deployer that hosts it, then deletes the
subscription document itself."""

import asyncio
from app.core.timeutils import utcnow

from app.core.config import get_settings
from app.core.logging import logger
from app.db.mongo import subscriptions_col
from app.services import deployer_service


async def _expire_once() -> None:
    now = utcnow()
    cursor = subscriptions_col().find({"status": "active", "expires_at": {"$lte": now}})
    async for sub in cursor:
        try:
            if sub.get("product_type") == "api_claimer" and sub.get("app_name") and sub.get("deploy_url"):
                auth_token = deployer_service.get_deployer_auth_token(sub["deploy_url"])
                if auth_token:
                    ok, res = await deployer_service.delete_container(
                        sub["app_name"], sub["deploy_url"], auth_token
                    )
                    if not ok:
                        logger.warning(
                            f"[SUB_EXPIRY] Failed to delete container {sub['app_name']} for "
                            f"subscription {sub['_id']}: {res.get('error')}"
                        )

            await subscriptions_col().delete_one({"_id": sub["_id"]})
        except Exception as e:
            logger.exception(f"[SUB_EXPIRY] Error expiring subscription {sub['_id']}: {e}")


async def run_forever() -> None:
    settings = get_settings()
    logger.info("Subscription expiry worker started")
    while True:
        try:
            await _expire_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception(f"[SUB_EXPIRY] top-level error: {e}")
        await asyncio.sleep(settings.POLL_INTERVAL_SECONDS)
