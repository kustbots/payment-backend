import httpx

from app.core.config import get_settings
from app.core.logging import logger


async def activate(stake_username: str, hours: int, api_base_url: str) -> bool:
    """Call the external Rebate Claimer API to activate a Stake username for N hours."""
    settings = get_settings()
    if not api_base_url:
        logger.warning("activate() called with no api_base_url configured; skipping external call")
        return False

    username_with_at = stake_username if stake_username.startswith("@") else f"@{stake_username}"
    params = {
        "user": username_with_at,
        "admin": settings.CLAIMER_ADMIN_TOKEN,
        "duration": hours,
    }
    url = f"{api_base_url}/auth"
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
        logger.info(f"[CLAIMER] Activated {username_with_at} for {hours}h on {api_base_url}")
        return True
    except Exception as e:
        logger.exception(f"[CLAIMER] Failed to activate {username_with_at} on {api_base_url}: {e}")
        return False


async def delete_user(stake_username: str, api_base_url: str) -> bool:
    settings = get_settings()
    if not api_base_url:
        return False
    username_with_at = stake_username if stake_username.startswith("@") else f"@{stake_username}"
    params = {"username": username_with_at, "admin": settings.CLAIMER_ADMIN_TOKEN}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{api_base_url}/delete_user", params=params)
            r.raise_for_status()
        return True
    except Exception as e:
        logger.exception(f"[CLAIMER] Failed to delete user {username_with_at} on {api_base_url}: {e}")
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(f"{api_base_url}/delete_user", params=params)
                r.raise_for_status()
            return True
        except Exception as e2:
            logger.exception(f"[CLAIMER] GET fallback also failed for {username_with_at}: {e2}")
            return False
