from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from threading import Lock
from typing import Any

from fastapi import Request

from .config import FRONTEND_ORIGIN, PUBLIC_API_URL, SESSION_COOKIE_NAME, SESSION_COOKIE_SAMESITE, SESSION_COOKIE_SECURE, STORAGE_ROOT

EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_rate_lock = Lock()
_rate_buckets: dict[str, deque[float]] = defaultdict(deque)


def rate_limit(key: str, limit: int, window_seconds: int) -> bool:
    now = time.monotonic()
    with _rate_lock:
        bucket = _rate_buckets[key]
        while bucket and now - bucket[0] > window_seconds:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True


def validate_email(email: str) -> str:
    clean = email.strip().lower()
    if len(clean) > 254 or not EMAIL_PATTERN.match(clean):
        raise ValueError("Enter a valid email address.")
    return clean


def validate_password(password: str) -> str:
    if len(password) < 8 or len(password) > 200:
        raise ValueError("Password must be 8–200 characters.")
    if not any(char.isalpha() for char in password) or not any(char.isdigit() for char in password):
        raise ValueError("Password must contain at least one letter and one number.")
    return password


def public_user(user: dict[str, Any] | None) -> dict[str, Any] | None:
    if not user:
        return None
    preferences = user.get("notification_preferences") or "{}"
    try:
        import json

        preferences = json.loads(preferences) if isinstance(preferences, str) else preferences
    except Exception:
        preferences = {}
    photo_url = None
    if user.get("profile_photo_path"):
        try:
            relative = (
                "/media/"
                + str(__import__("pathlib").Path(user["profile_photo_path"]).resolve().relative_to(STORAGE_ROOT.resolve())).replace("\\", "/")
            )
            photo_url = f"{PUBLIC_API_URL.rstrip('/')}{relative}" if PUBLIC_API_URL else relative
        except Exception:
            photo_url = None
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user.get("name") or "",
        "profile_photo_url": photo_url,
        "country": user.get("country") or "",
        "language": user.get("language") or "en",
        "timezone": user.get("timezone") or "UTC",
        "plan_id": user.get("plan_id") or "free",
        "email_verified": bool(user.get("email_verified")),
        "is_admin": bool(user.get("is_admin")),
        "notification_preferences": preferences,
        "theme": user.get("theme") or "dark",
        "created_at": user.get("created_at"),
        "last_login_at": user.get("last_login_at"),
    }


def session_user(request: Request) -> dict[str, Any] | None:
    return getattr(request.state, "auth_session", None)


def set_session_cookie(response: Any, session: dict[str, Any]) -> None:
    """Set the session cookie on a response.

    Uses SESSION_COOKIE_* settings from config. If `session.get("remember_me")` is truthy
    the cookie will be persisted for 30 days; otherwise it will be a session cookie.
    """
    max_age = 30 * 86400 if session.get("remember_me") else None
    # Starlette/FastAPI response.set_cookie accepts None for max_age
    response.set_cookie(
        SESSION_COOKIE_NAME,
        str(session["token"]),
        httponly=True,
        secure=SESSION_COOKIE_SECURE,
        samesite=SESSION_COOKIE_SAMESITE,
        max_age=max_age,
        path="/",
    )


def clear_session_cookie(response: Any) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")


def auth_payload(user: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
    return {
        "authenticated": True,
        "user": public_user(user),
        "csrf_token": session["csrf_token"],
        "session": {"id": session["session_id"], "expires_at": session["expires_at"]},
    }


def frontend_redirect(path: str = "/app") -> str:
    return f"{FRONTEND_ORIGIN.rstrip('/')}{path}"
