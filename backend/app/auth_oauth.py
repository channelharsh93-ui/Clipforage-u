from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from . import auth_db
from .config import FRONTEND_ORIGIN

OAUTH_CONFIG = {
    "google": {
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "userinfo": "https://openidconnect.googleapis.com/v1/userinfo",
        "scope": "openid email profile",
        "client_id_env": "GOOGLE_CLIENT_ID",
        "client_secret_env": "GOOGLE_CLIENT_SECRET",
    },
    "github": {
        "authorize": "https://github.com/login/oauth/authorize",
        "token": "https://github.com/login/oauth/access_token",
        "userinfo": "https://api.github.com/user",
        "scope": "read:user user:email",
        "client_id_env": "GITHUB_CLIENT_ID",
        "client_secret_env": "GITHUB_CLIENT_SECRET",
    },
}


def _config(provider: str) -> dict[str, str]:
    import os
    if provider not in OAUTH_CONFIG:
        raise ValueError("Unsupported OAuth provider.")
    config = OAUTH_CONFIG[provider]
    client_id = os.getenv(config["client_id_env"], "")
    client_secret = os.getenv(config["client_secret_env"], "")
    if not client_id or not client_secret:
        raise RuntimeError(f"{provider.title()} Sign-In is not configured.")
    return {**config, "client_id": client_id, "client_secret": client_secret}


def create_state(provider: str, redirect_uri: str) -> str:
    state = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    conn = auth_db.db.connect()
    try:
        conn.execute("INSERT INTO auth_oauth_states(state,provider,redirect_uri,created_at,expires_at) VALUES(?,?,?,?,?)", (state, provider, redirect_uri, now.isoformat(), (now + timedelta(minutes=10)).isoformat()))
        conn.commit()
    finally:
        conn.close()
    return state


def consume_state(state: str, provider: str) -> dict[str, Any] | None:
    conn = auth_db.db.connect()
    try:
        row = conn.execute("SELECT * FROM auth_oauth_states WHERE state=? AND provider=?", (state, provider)).fetchone()
        if not row or auth_db.datetime_from(row["expires_at"]) <= datetime.now(timezone.utc):
            return None
        conn.execute("DELETE FROM auth_oauth_states WHERE state=?", (state,))
        conn.commit()
        return dict(row)
    finally:
        conn.close()


def authorization_url(provider: str, redirect_uri: str) -> str:
    from urllib.parse import urlencode
    config = _config(provider)
    state = create_state(provider, redirect_uri)
    params = {"client_id": config["client_id"], "redirect_uri": redirect_uri, "response_type": "code", "scope": config["scope"], "state": state}
    if provider == "google":
        params.update({"access_type": "offline", "prompt": "select_account"})
    return f"{config['authorize']}?{urlencode(params)}"


def complete(provider: str, code: str, state: str) -> dict[str, Any]:
    import os
    stored = consume_state(state, provider)
    if not stored:
        raise RuntimeError("OAuth state is invalid or expired.")
    config = _config(provider)
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        token_response = client.post(config["token"], data={"client_id": config["client_id"], "client_secret": config["client_secret"], "code": code, "redirect_uri": stored["redirect_uri"], "grant_type": "authorization_code"}, headers={"Accept": "application/json"})
        token_response.raise_for_status()
        token_data = token_response.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise RuntimeError("OAuth provider did not return an access token.")
        user_response = client.get(config["userinfo"], headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json", "User-Agent": "ClipForge"})
        user_response.raise_for_status()
        profile = user_response.json()
        email = str(profile.get("email") or "").strip().lower()
        provider_user_id = str(profile.get("sub") or profile.get("id") or "")
        if provider == "github" and not email:
            emails_response = client.get("https://api.github.com/user/emails", headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json", "User-Agent": "ClipForge"})
            if emails_response.is_success:
                email = next((str(item.get("email", "")).lower() for item in emails_response.json() if item.get("primary") and item.get("verified")), "")
        if not email or not provider_user_id:
            raise RuntimeError("The OAuth provider did not return a verified email address.")
    user = auth_db.get_oauth_user(provider, provider_user_id) or auth_db.get_user_by_email(email)
    if not user:
        user = auth_db.create_user(email, secrets.token_urlsafe(32), str(profile.get("name") or profile.get("login") or email.split("@", 1)[0]))
    auth_db.upsert_oauth_account(user["id"], provider, provider_user_id, email, profile)
    auth_db.update_user(user["id"], email_verified=1, profile_photo_path=profile.get("picture") or profile.get("avatar_url") or None)
    return auth_db.get_user(user["id"])  # type: ignore[return-value]
