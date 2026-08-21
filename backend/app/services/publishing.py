from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import db, social_db
from ..plans import has_entitlement
from .social_platforms import get_provider
from .social_service import _runtime_connection, provider_status


def _platform_capability(platform_id: str, key: str) -> bool:
    for item in provider_status():
        if item["id"] == platform_id:
            return bool(item.get("capabilities", {}).get(key))
    return False


def queue_clip_publish(
    clip_id: str, platform: str, account_id: str | None, caption: str, title: str,
    hashtags: list[str], visibility: str, scheduled_at: str | None, rights_acknowledged: bool,
) -> dict[str, Any]:
    if not rights_acknowledged:
        raise RuntimeError("Confirm that you own or have authorization to publish this content.")
    if not has_entitlement("platform_publish"):
        raise RuntimeError("Pro at ₹99/month is required for direct platform publishing. Download remains free.")
    clip = db.get_clip(clip_id)
    if not clip:
        raise RuntimeError("Clip not found.")
    if not clip.get("video_path") or not Path(clip["video_path"]).exists():
        raise RuntimeError("Render the clip before adding it to the publishing queue.")
    if not _platform_capability(platform, "publish"):
        raise RuntimeError(f"Official publishing is not currently available for {platform.title()} in this Free Mode MVP.")
    connections = [c for c in social_db.list_connections(platform) if c.get("status") == "connected"]
    if account_id:
        connections = [c for c in connections if c.get("account_id") == account_id]
    if not connections:
        raise RuntimeError(f"Connect an authorized {platform.title()} account before publishing.")
    return social_db.create_publish_item(clip_id, platform, connections[0]["account_id"], caption, title, hashtags, clip.get("thumbnail_path"), visibility, scheduled_at)


def publish_item(item_id: str) -> dict[str, Any]:
    item = social_db.get_publish_item(item_id)
    if not item:
        raise RuntimeError("Publishing queue item not found.")
    clip = db.get_clip(item["clip_id"])
    if not clip or not clip.get("video_path"):
        raise RuntimeError("The rendered clip is no longer available.")
    connections = [c for c in social_db.list_connections(item["platform"]) if c.get("account_id") == item.get("account_id")]
    if not connections:
        raise RuntimeError("The connected account is no longer available. Reconnect it before retrying.")
    connection = _runtime_connection(connections[0]["id"])
    provider = get_provider(item["platform"])
    social_db.update_publish_item(item_id, status="Publishing", error=None)
    payload = {
        "local_path": clip["video_path"], "thumbnail_path": item.get("thumbnail_path"), "caption": item.get("caption", ""), "title": item.get("title", ""),
        "hashtags": item.get("hashtags", []), "visibility": item.get("visibility", "private"), "account_id": item.get("account_id"),
    }
    try:
        result = provider.publish_video(connection, payload)
        if not result.get("supported") or not result.get("published"):
            error = result.get("reason") or "The platform did not publish the clip."
            return social_db.update_publish_item(item_id, status="Failed", error=error)  # type: ignore[return-value]
        return social_db.update_publish_item(item_id, status="Published", remote_id=result.get("remote_id"), error=None)  # type: ignore[return-value]
    except Exception as exc:
        return social_db.update_publish_item(item_id, status="Failed", error=str(exc)[-1000:])  # type: ignore[return-value]


def retry_item(item_id: str) -> dict[str, Any]:
    item = social_db.get_publish_item(item_id)
    if not item:
        raise RuntimeError("Publishing queue item not found.")
    social_db.update_publish_item(item_id, status="Ready", error=None)
    return publish_item(item_id)
