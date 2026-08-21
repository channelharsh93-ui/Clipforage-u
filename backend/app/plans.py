from __future__ import annotations

import os
from typing import Any

from . import social_db
from .auth_context import current_user_id
from .config import FREE_PLAN_CLIPS, FREE_PLAN_VIDEOS


PLANS: dict[str, dict[str, Any]] = {
    "free": {
        "id": "free", "name": "Free Mode", "price_inr_monthly": 0, "badge": "Always free locally",
        "description": f"Create up to {FREE_PLAN_CLIPS} short clips per day with the full local editing workflow.",
        "limits": {"projects": 25, "monthly_source_minutes": 300, "daily_processing_jobs": FREE_PLAN_VIDEOS, "daily_clips": FREE_PLAN_CLIPS, "clips_per_project": FREE_PLAN_CLIPS, "storage_gb": 20},
        "features": ["Local video processing", "Local transcription", f"Up to {FREE_PLAN_CLIPS} clips per day", "Captions, crop, edit, download", "Basic hook and title", "Non-intrusive sponsorships"],
        "entitlements": {"full_content_pack": False, "seo": False, "platform_publish": False, "social_import": False, "batch_processing": False, "priority_processing": False, "premium_caption_styles": False, "remove_watermark": False, "ads": True},
        "billing_required": False,
    },
    "pro": {
        "id": "pro", "name": "Pro", "price_inr_monthly": 99, "badge": "₹99 / month",
        "description": "Unlock full content intelligence and official platform publishing when your accounts are connected.",
        "limits": {"projects": 500, "monthly_source_minutes": 5000, "daily_processing_jobs": 500, "daily_clips": 100, "clips_per_project": 30, "storage_gb": 100},
        "features": ["Everything in Free", "Full hooks, titles, descriptions", "Hashtags, keywords, SEO score", "Platform-specific content packs", "Official publishing controls", "Batch and priority processing", "Premium captions and ad-free workspace"],
        "entitlements": {"full_content_pack": True, "seo": True, "platform_publish": True, "social_import": True, "batch_processing": True, "priority_processing": True, "premium_caption_styles": True, "remove_watermark": True, "ads": False},
        "billing_required": True,
    },
}


def current_plan_id(user_id: str | None = None) -> str:
    scoped_user_id = user_id or current_user_id()
    if scoped_user_id:
        try:
            from .billing_db import active_plan_for_user
            active = active_plan_for_user(scoped_user_id)
            if active in PLANS:
                return active
        except Exception:
            pass
        try:
            from .auth_db import get_user
            user = get_user(scoped_user_id)
            configured = str((user or {}).get("plan_id") or "free").lower()
            if configured in PLANS:
                return configured
        except Exception:
            pass
    configured = social_db.get_setting("subscription_plan", None)
    plan = str(configured or os.getenv("USER_PLAN", "free")).lower()
    if plan == "premium":
        plan = "pro"
    return plan if plan in PLANS else "free"


def list_plans() -> list[dict[str, Any]]:
    return list(PLANS.values())


def current_plan(user_id: str | None = None) -> dict[str, Any]:
    return PLANS[current_plan_id(user_id)]


def has_entitlement(feature: str, user_id: str | None = None) -> bool:
    return bool(current_plan(user_id).get("entitlements", {}).get(feature, False))


def current_subscription() -> dict[str, Any]:
    from .billing import billing_status
    user_id = current_user_id()
    plan_id = current_plan_id(user_id)
    plan = PLANS[plan_id]
    provider = billing_status()
    subscription = None
    if user_id:
        try:
            from .billing_db import get_current_subscription
            subscription = get_current_subscription(user_id)
        except Exception:
            subscription = None
    return {
        "plan": plan,
        "plan_id": plan_id,
        "billing_configured": bool(provider.get("configured")),
        "billing_status": "configured" if provider.get("configured") else "not_configured",
        "source": "verified billing subscription for the signed-in user" if user_id else "local subscription setting / USER_PLAN environment setting",
        "subscription": subscription,
        "message": "No payment provider is connected. Pro is locked until a verified payment or subscription event activates it." if plan_id == "free" else "Pro entitlement is active for this local account.",
    }
