from __future__ import annotations

from typing import Any

from .user_settings import get_user_settings, set_user_settings


def privacy_mode() -> bool:
    return bool(get_user_settings().get("privacy_mode", True))


def set_privacy_mode(value: bool) -> bool:
    settings = get_user_settings()
    settings["privacy_mode"] = bool(value)
    set_user_settings(settings)
    return bool(value)


def privacy_status() -> dict[str, Any]:
    enabled = privacy_mode()
    return {
        "enabled": enabled,
        "cloud_ai": False,
        "external_analytics": False,
        "official_social_apis": False if enabled else "opt-in",
        "message": "No cloud requests, analytics uploads, or external AI calls are made while Privacy Mode is on." if enabled else "Privacy Mode is off; official APIs remain separately opt-in.",
    }
