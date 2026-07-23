import json
import random
import string

import httpx

from app.core.config import get_settings
from app.core.logging import logger
from app.db.mongo import subscriptions_col


async def get_available_deployer(tried_urls: set[str] | None = None) -> dict | None:
    settings = get_settings()
    tried = tried_urls or set()
    for deployer in settings.deployers:
        if deployer["url"] in tried:
            continue
        count = await subscriptions_col().count_documents(
            {"deploy_url": deployer["url"], "status": "active"}
        )
        if count < deployer.get("limit", 100):
            return deployer
    return None


def generate_unique_app_name(username: str) -> str:
    clean_user = username.lstrip("@").lower()
    clean_user = "".join(c for c in clean_user if c.isalnum() or c == "-")
    if len(clean_user) > 18:
        clean_user = clean_user[:18]
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
    return f"api-cl-{clean_user}-{suffix}"


async def deploy_container(
    session_token: str,
    app_name: str,
    deploy_url: str,
    auth_token: str,
    mirror_site: str,
    claimer_settings: dict | None = None,
) -> tuple[bool, dict]:
    """Deploy a container via the given deployer, parsing its SSE progress stream.

    claimer_settings (currency/vault/process_all/drops) are forwarded into the
    deploy payload only where set -- None values are omitted so the deployer
    falls back to its own defaults, matching the legacy bot's behavior.
    """
    url = f"{deploy_url}/deploy"
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    payload = {"session_token": session_token, "app_name": app_name, "MIRROR_SITE": mirror_site}
    if claimer_settings:
        for key in ("currency", "vault", "process_all", "drops"):
            value = claimer_settings.get(key)
            if value is not None:
                payload[key] = value

    try:
        async with httpx.AsyncClient(timeout=7200) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as r:
                if r.status_code >= 400:
                    body = await r.aread()
                    return False, {"error": f"HTTP {r.status_code}: {body.decode(errors='replace')}"}

                last_status = None
                async for line in r.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    last_status = data
                    status = data.get("status", "")
                    if status == "completed":
                        return True, data
                    if status in ("error", "build_failed", "build_timeout"):
                        return False, data

                if last_status and last_status.get("success") is True:
                    return True, last_status
                return False, {"error": "Stream ended without completion status", "last_status": last_status}
    except Exception as e:
        logger.exception(f"[DEPLOY] Failed to deploy container {app_name}: {e}")
        return False, {"error": str(e)}


def get_deployer_auth_token(deploy_url: str) -> str | None:
    settings = get_settings()
    for deployer in settings.deployers:
        if deployer["url"] == deploy_url:
            return deployer["token"]
    return None


async def apply_container_settings(
    deploy_url: str, auth_token: str, app_name: str, settings_payload: dict
) -> tuple[bool, dict]:
    """PATCH settings (currency/vault/process_all/drops) on an already-deployed
    container. Only non-None keys in settings_payload are sent."""
    url = f"{deploy_url}/apps/{app_name}/settings"
    headers = {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}
    body = {k: v for k, v in settings_payload.items() if v is not None}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.patch(url, headers=headers, json=body)
        if r.status_code >= 400:
            return False, {"error": f"HTTP {r.status_code}: {r.text}"}
        try:
            return True, r.json()
        except Exception:
            return True, {"status": "ok"}
    except Exception as e:
        logger.exception(f"[SETTINGS] Failed to apply settings for {app_name}: {e}")
        return False, {"error": str(e)}


async def delete_container(app_name: str, deploy_url: str, auth_token: str) -> tuple[bool, dict]:
    url = f"{deploy_url}/apps/{app_name}"
    headers = {"Authorization": f"Bearer {auth_token}"}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.delete(url, headers=headers)
        if r.status_code == 200:
            return True, r.json()
        text = r.text.lower()
        if "not_found" in text or "couldn't find that app" in text:
            return True, {"status": "already_deleted"}
        return False, {"error": f"HTTP {r.status_code}: {r.text}"}
    except Exception as e:
        logger.exception(f"[DEPLOY] Failed to delete container {app_name}: {e}")
        return False, {"error": str(e)}
