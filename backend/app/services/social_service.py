from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from .. import db, social_db
from ..config import ALLOW_OFFICIAL_APIS, ALLOWED_EXTENSIONS, FREE_MODE_DEFAULT, STORAGE_ROOT, max_file_size_bytes, project_root
from ..plans import has_entitlement
from ..privacy import privacy_mode
from .ffmpeg import probe_video
from .social_platforms import get_provider, list_provider_metadata
from ..storage_guard import storage_status
from .token_store import get_token_store


def free_mode() -> bool:
    value = social_db.get_setting("free_mode", FREE_MODE_DEFAULT)
    if not isinstance(value, bool):
        return str(value).lower() not in {"0", "false", "off"}
    return value


def set_free_mode(value: bool) -> bool:
    social_db.set_setting("free_mode", bool(value))
    return bool(value)


def provider_status() -> list[dict[str, Any]]:
    connections = social_db.list_connections()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for connection in connections:
        grouped.setdefault(connection["provider_id"], []).append(connection)
    output = []
    for meta in list_provider_metadata():
        item = dict(meta)
        # Environment configuration only means the official app credentials exist;
        # it is deliberately not reported as connected. Official API access is a
        # separate opt-in guard so Free Mode never makes network calls silently.
        item["official_api_enabled"] = ALLOW_OFFICIAL_APIS
        item["configured"] = bool(meta.get("configured")) and ALLOW_OFFICIAL_APIS
        item["connections"] = grouped.get(meta["id"], [])
        item["connected"] = any(c.get("status") == "connected" for c in item["connections"])
        item["connection_count"] = len(item["connections"])
        output.append(item)
    return output


def start_connect(platform_id: str, purpose: str, redirect_uri: str) -> dict[str, Any]:
    provider = get_provider(platform_id)
    if privacy_mode():
        return {"ok": False, "configured": False, "platform": platform_id, "message": "Privacy Mode is on. External social API requests are disabled; upload a local video instead."}
    if not ALLOW_OFFICIAL_APIS:
        return {
            "ok": False,
            "configured": False,
            "platform": platform_id,
            "message": "Official social API access is disabled by default. Set ALLOW_OFFICIAL_APIS=true only after configuring the platform's official developer app.",
        }
    if not provider.is_configured():
        return {
            "ok": False,
            "configured": False,
            "platform": platform_id,
            "message": "This platform is not configured yet. Add the official developer-app credentials to the backend environment; ClipForge will not create a fake connection.",
        }
    state = secrets.token_urlsafe(32)
    social_db.create_oauth_state(platform_id, purpose, redirect_uri, state)
    auth = provider.authenticate(redirect_uri, state, purpose)
    return {"ok": True, "configured": True, "platform": platform_id, "purpose": purpose, "authorization_url": auth["authorization_url"], "state": state}


def complete_connect(platform_id: str, code: str, state: str) -> dict[str, Any]:
    saved = social_db.consume_oauth_state(state)
    if not saved or saved.get("provider_id") != platform_id:
        raise RuntimeError("The OAuth state is invalid or expired. Start the connection again.")
    provider = get_provider(platform_id)
    token_payload = provider.exchange_code(code, saved["redirect_uri"])
    access_token = token_payload.get("access_token")
    if not access_token:
        raise RuntimeError("The platform did not return an access token. No connection was stored.")
    account = provider.get_account(access_token)
    scopes = token_payload.get("scope") or token_payload.get("scopes") or []
    if isinstance(scopes, str):
        scopes = scopes.replace(",", " ").split()
    stored = social_db.save_connection(
        provider_id=platform_id, account_id=str(account.get("account_id")), account_name=account.get("account_name", provider.meta.name),
        token_encrypted=get_token_store().encrypt(access_token) or "", refresh_token_encrypted=get_token_store().encrypt(token_payload.get("refresh_token")),
        expires_at=token_payload.get("expires_at"), scopes=list(scopes), metadata=account.get("metadata") or {},
    )
    return {"ok": True, "platform": platform_id, "connection": social_db._public_connection(stored)}


def _runtime_connection(connection_id: str) -> dict[str, Any]:
    row = social_db.get_connection(connection_id)
    if not row:
        raise RuntimeError("Connected account not found.")
    row = social_db.decryptable_connection(row)
    row["access_token"] = get_token_store().decrypt(row.get("token_encrypted"))
    row["refresh_token"] = get_token_store().decrypt(row.get("refresh_token_encrypted"))
    if not row.get("access_token"):
        raise RuntimeError("The stored connection could not be unlocked. Reconnect the account.")
    return row


def list_videos(platform_id: str, connection_id: str) -> list[dict[str, Any]]:
    if privacy_mode():
        raise RuntimeError("Privacy Mode is on. External social API requests are disabled.")
    provider = get_provider(platform_id)
    connection = _runtime_connection(connection_id)
    try:
        return provider.get_user_videos(connection)
    except Exception as exc:
        social_db.mark_connection_error(connection_id, str(exc))
        raise RuntimeError(f"Could not read videos from {provider.meta.name}: {str(exc)[-500:]}")


def _download_authorized_media(url: str, headers: dict[str, str], destination: Path) -> int:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise RuntimeError("The platform returned an invalid media URL.")
    written = 0
    with httpx.Client(follow_redirects=True, timeout=120) as client:
        with client.stream("GET", url, headers=headers) as response:
            if response.status_code >= 400:
                raise RuntimeError(f"The platform refused the authorized media request (HTTP {response.status_code}).")
            content_type = response.headers.get("content-type", "")
            if not content_type.startswith("video/"):
                raise RuntimeError("The platform response was not a video file.")
            with destination.open("wb") as output:
                for chunk in response.iter_bytes(1024 * 1024):
                    written += len(chunk)
                    if written > max_file_size_bytes():
                        raise RuntimeError("The imported video exceeds the configured Free Mode size limit.")
                    output.write(chunk)
    return written


def import_video(platform_id: str, connection_id: str, video: dict[str, Any], project_name: str, rights_acknowledged: bool) -> dict[str, Any]:
    if not rights_acknowledged:
        raise RuntimeError("Confirm that you own or have authorization to edit and publish this content.")
    if not has_entitlement("social_import"):
        raise RuntimeError("Pro at ₹99/month is required for direct social-platform import. Local upload remains free.")
    provider = get_provider(platform_id)
    connection = _runtime_connection(connection_id)
    media = provider.get_video_media(connection, video)
    if not media.get("supported"):
        raise RuntimeError(media.get("reason") or f"{provider.meta.name} does not provide an available video-import method for this workflow. Upload the video file instead.")
    project = db.create_project(project_name or video.get("title") or f"{provider.meta.name} video", True, source_type=f"social:{platform_id}", source_url=video.get("permalink"))
    root = project_root(project["id"])
    destination = root / "original.mp4"
    try:
        _download_authorized_media(media["url"], media.get("headers") or {}, destination)
        metadata = probe_video(destination)
        db.update_project(project["id"], original_path=str(destination), original_filename=video.get("title") or f"{platform_id}-video.mp4", status="uploaded", progress=0, current_stage="Ready to analyze", error=None, **metadata)
    except Exception:
        import shutil
        shutil.rmtree(root, ignore_errors=True)
        db.delete_project(project["id"])
        raise
    return db.get_project(project["id"])  # type: ignore[return-value]


def cost_status() -> dict[str, Any]:
    enabled = free_mode()
    return {
        "free_mode": enabled,
        "ai_processing": {"status": "Local / Free", "detail": "Open-source local transcription and deterministic analysis"},
        "video_processing": {"status": "Local / Free", "detail": "FFmpeg and OpenCV on this machine"},
        "storage": {"status": "Local / Free", "detail": "SQLite and local filesystem", "usage": storage_status()},
        "social_apis": {"status": "Official APIs disabled" if not ALLOW_OFFICIAL_APIS else "Platform limits apply", "detail": "Official developer APIs are opt-in and no paid social service is configured", "official_api_enabled": ALLOW_OFFICIAL_APIS},
        "paid_services": {"status": "None configured", "detail": "ClipForge will not silently call paid providers"},
        "disabled_paid_features": [] if not enabled else ["Cloud GPU processing", "Paid transcription providers", "Cloud storage", "Paid music libraries"],
    }
