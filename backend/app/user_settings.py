from __future__ import annotations

from typing import Any

from . import social_db
from .auth_context import current_user_id
from .config import PRIVACY_MODE_DEFAULT

DEFAULT_USER_SETTINGS: dict[str, Any] = {
    "language": "en",
    "default_clip_length": 30,
    "default_aspect": "9:16",
    "caption_style": "bold",
    "caption_position": "bottom",
    "hook_style": "curiosity",
    "hashtag_count": 10,
    "default_platform": "youtube_shorts",
    "tone": "casual",
    "brand_name": "",
    "brand_description": "",
    "privacy_mode": PRIVACY_MODE_DEFAULT,
}


def _settings_key() -> str:
    user_id = current_user_id()
    return f"user_settings:{user_id}" if user_id else "user_settings"


def get_user_settings() -> dict[str, Any]:
    saved = social_db.get_setting(_settings_key(), {})
    result = dict(DEFAULT_USER_SETTINGS)
    if isinstance(saved, dict):
        result.update({key: value for key, value in saved.items() if key in DEFAULT_USER_SETTINGS})
    return result


def set_user_settings(values: dict[str, Any]) -> dict[str, Any]:
    result = dict(DEFAULT_USER_SETTINGS)
    result.update({key: value for key, value in values.items() if key in DEFAULT_USER_SETTINGS})
    if result["language"] not in {"en", "hi"}:
        result["language"] = "en"
    if result["default_clip_length"] not in {15, 30, 45, 60}:
        result["default_clip_length"] = 30
    if result["default_aspect"] not in {"9:16", "1:1", "16:9"}:
        result["default_aspect"] = "9:16"
    if result["caption_style"] not in {"clean", "bold", "creator", "podcast", "minimal", "high-energy"}:
        result["caption_style"] = "bold"
    if result["caption_position"] not in {"top", "middle", "bottom"}:
        result["caption_position"] = "bottom"
    if result["hook_style"] not in {"curiosity", "question", "bold", "story", "shock", "minimal"}:
        result["hook_style"] = "curiosity"
    if result["hashtag_count"] not in {5, 10, 20}:
        result["hashtag_count"] = 10
    if result["default_platform"] not in {"youtube_shorts", "instagram_reels", "tiktok", "facebook"}:
        result["default_platform"] = "youtube_shorts"
    if result["tone"] not in {"professional", "funny", "bold", "educational", "casual", "premium", "gen-z", "minimal"}:
        result["tone"] = "casual"
    result["brand_name"] = str(result.get("brand_name", ""))[:120]
    result["brand_description"] = str(result.get("brand_description", ""))[:500]
    result["privacy_mode"] = bool(result.get("privacy_mode", True))
    social_db.set_setting(_settings_key(), result)
    return result
