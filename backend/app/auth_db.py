from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from . import db
from .config import ADMIN_EMAILS

PASSWORD_ITERATIONS = 310_000
TOKEN_BYTES = 32


def _now() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return _now().isoformat()


def _hash_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def init_auth_db() -> None:
    conn = db.connect()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT,
                name TEXT NOT NULL DEFAULT '',
                profile_photo_path TEXT,
                country TEXT NOT NULL DEFAULT '',
                language TEXT NOT NULL DEFAULT 'en',
                timezone TEXT NOT NULL DEFAULT 'UTC',
                plan_id TEXT NOT NULL DEFAULT 'free',
                email_verified INTEGER NOT NULL DEFAULT 0,
                is_admin INTEGER NOT NULL DEFAULT 0,
                notification_preferences TEXT NOT NULL DEFAULT '{}',
                theme TEXT NOT NULL DEFAULT 'dark',
                created_at TEXT NOT NULL,
                last_login_at TEXT,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS auth_sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token_hash TEXT NOT NULL UNIQUE,
                csrf_token TEXT NOT NULL,
                user_agent TEXT NOT NULL DEFAULT '',
                ip_address TEXT NOT NULL DEFAULT '',
                device_name TEXT NOT NULL DEFAULT '',
                remember_me INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                revoked_at TEXT
            );
            CREATE TABLE IF NOT EXISTS auth_tokens (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                kind TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL,
                used_at TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS oauth_accounts (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                provider TEXT NOT NULL,
                provider_user_id TEXT NOT NULL,
                email TEXT NOT NULL DEFAULT '',
                profile_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(provider, provider_user_id)
            );
            CREATE TABLE IF NOT EXISTS email_outbox (
                id TEXT PRIMARY KEY,
                user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
                kind TEXT NOT NULL,
                recipient TEXT NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                created_at TEXT NOT NULL,
                sent_at TEXT
            );
            CREATE TABLE IF NOT EXISTS auth_oauth_states (
                state TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                redirect_uri TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id, revoked_at, expires_at);
            CREATE INDEX IF NOT EXISTS idx_auth_tokens_lookup ON auth_tokens(token_hash, kind, used_at);
            CREATE INDEX IF NOT EXISTS idx_email_outbox_created ON email_outbox(created_at DESC);
            """
        )
        conn.commit()
    finally:
        conn.close()


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)).hex()
        return hmac.compare_digest(candidate, digest_hex)
    except (ValueError, TypeError):
        return False


def create_user(email: str, password: str, name: str = "") -> dict[str, Any]:
    user_id = secrets.token_urlsafe(18)
    now = now_iso()
    clean_email = email.strip().lower()
    password_hash = hash_password(password)
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO users(id,email,password_hash,name,is_admin,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (user_id, clean_email, password_hash, name.strip()[:120], int(clean_email in ADMIN_EMAILS), now, now),
        )
        conn.commit()
    finally:
        conn.close()
    return get_user(user_id)  # type: ignore[return-value]


def get_user(user_id: str) -> dict[str, Any] | None:
    conn = db.connect()
    try:
        return _row(conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())
    finally:
        conn.close()


def get_user_by_email(email: str) -> dict[str, Any] | None:
    conn = db.connect()
    try:
        return _row(conn.execute("SELECT * FROM users WHERE email=?", (email.strip().lower(),)).fetchone())
    finally:
        conn.close()


def update_user(user_id: str, **fields: Any) -> dict[str, Any] | None:
    allowed = {"name", "profile_photo_path", "country", "language", "timezone", "plan_id", "notification_preferences", "theme", "email_verified", "last_login_at", "updated_at"}
    data = {key: value for key, value in fields.items() if key in allowed}
    if "notification_preferences" in data and not isinstance(data["notification_preferences"], str):
        data["notification_preferences"] = json.dumps(data["notification_preferences"])
    data["updated_at"] = now_iso()
    assignments = ", ".join(f"{key}=?" for key in data)
    conn = db.connect()
    try:
        conn.execute(f"UPDATE users SET {assignments} WHERE id=?", [*data.values(), user_id])
        conn.commit()
    finally:
        conn.close()
    return get_user(user_id)


def change_password(user_id: str, password: str) -> dict[str, Any] | None:
    password_hash = hash_password(password)
    conn = db.connect()
    try:
        conn.execute("UPDATE users SET password_hash=?, updated_at=? WHERE id=?", (password_hash, now_iso(), user_id))
        conn.commit()
    finally:
        conn.close()
    revoke_all_sessions(user_id)
    return get_user(user_id)


def create_session(user_id: str, user_agent: str = "", ip_address: str = "", remember_me: bool = False) -> dict[str, str | int]:
    session_id = secrets.token_urlsafe(18)
    raw_token = secrets.token_urlsafe(TOKEN_BYTES)
    csrf_token = secrets.token_urlsafe(24)
    now = _now()
    expires = now + (timedelta(days=30) if remember_me else timedelta(hours=12))
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO auth_sessions(id,user_id,token_hash,csrf_token,user_agent,ip_address,device_name,remember_me,created_at,last_seen_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (session_id, user_id, _hash_token(raw_token), csrf_token, user_agent[:300], ip_address[:80], _device_name(user_agent), int(remember_me), now.isoformat(), now.isoformat(), expires.isoformat()),
        )
        conn.execute("UPDATE users SET last_login_at=?, updated_at=? WHERE id=?", (now.isoformat(), now.isoformat(), user_id))
        conn.commit()
    finally:
        conn.close()
    return {"session_id": session_id, "token": raw_token, "csrf_token": csrf_token, "expires_at": expires.isoformat(), "remember_me": bool(remember_me)}


def _device_name(user_agent: str) -> str:
    value = user_agent.lower()
    browser = "Browser"
    for name in ("edg", "chrome", "firefox", "safari"):
        if name in value:
            browser = "Edge" if name == "edg" else name.title()
            break
    platform = "Mobile" if "mobile" in value or "android" in value or "iphone" in value else "Desktop"
    return f"{browser} · {platform}"


def get_session(raw_token: str | None) -> dict[str, Any] | None:
    if not raw_token:
        return None
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT s.*, u.email, u.name, u.plan_id, u.email_verified, u.is_admin FROM auth_sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.revoked_at IS NULL",
            (_hash_token(raw_token),),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        if datetime_from(result["expires_at"]) <= _now():
            conn.execute("UPDATE auth_sessions SET revoked_at=? WHERE id=?", (now_iso(), result["id"]))
            conn.commit()
            return None
        conn.execute("UPDATE auth_sessions SET last_seen_at=? WHERE id=?", (now_iso(), result["id"]))
        conn.commit()
        return result
    finally:
        conn.close()


def datetime_from(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def verify_csrf(session_id: str, csrf_token: str | None) -> bool:
    if not csrf_token:
        return False
    conn = db.connect()
    try:
        row = conn.execute("SELECT csrf_token FROM auth_sessions WHERE id=? AND revoked_at IS NULL", (session_id,)).fetchone()
        return bool(row and hmac.compare_digest(str(row["csrf_token"]), csrf_token))
    finally:
        conn.close()


def revoke_session(session_id: str) -> None:
    conn = db.connect()
    try:
        conn.execute("UPDATE auth_sessions SET revoked_at=? WHERE id=?", (now_iso(), session_id))
        conn.commit()
    finally:
        conn.close()


def revoke_all_sessions(user_id: str, except_session_id: str | None = None) -> None:
    conn = db.connect()
    try:
        if except_session_id:
            conn.execute("UPDATE auth_sessions SET revoked_at=? WHERE user_id=? AND id<>? AND revoked_at IS NULL", (now_iso(), user_id, except_session_id))
        else:
            conn.execute("UPDATE auth_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (now_iso(), user_id))
        conn.commit()
    finally:
        conn.close()


def list_sessions(user_id: str) -> list[dict[str, Any]]:
    conn = db.connect()
    try:
        return [dict(row) for row in conn.execute("SELECT id,device_name,user_agent,ip_address,remember_me,created_at,last_seen_at,expires_at FROM auth_sessions WHERE user_id=? AND revoked_at IS NULL ORDER BY last_seen_at DESC", (user_id,)).fetchall()]
    finally:
        conn.close()


def create_one_time_token(user_id: str, kind: str, hours: int = 24) -> str:
    raw = secrets.token_urlsafe(TOKEN_BYTES)
    now = _now()
    conn = db.connect()
    try:
        conn.execute("INSERT INTO auth_tokens(id,user_id,kind,token_hash,expires_at,created_at) VALUES(?,?,?,?,?,?)", (secrets.token_urlsafe(15), user_id, kind, _hash_token(raw), (now + timedelta(hours=hours)).isoformat(), now.isoformat()))
        conn.commit()
    finally:
        conn.close()
    return raw


def consume_one_time_token(raw: str, kind: str) -> dict[str, Any] | None:
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM auth_tokens WHERE token_hash=? AND kind=? AND used_at IS NULL", (_hash_token(raw), kind)).fetchone()
        if not row or datetime_from(row["expires_at"]) <= _now():
            return None
        conn.execute("UPDATE auth_tokens SET used_at=? WHERE id=?", (now_iso(), row["id"]))
        conn.commit()
        return dict(row)
    finally:
        conn.close()


def queue_email(user_id: str | None, recipient: str, kind: str, subject: str, body: str) -> dict[str, Any]:
    message_id = secrets.token_urlsafe(15)
    conn = db.connect()
    try:
        conn.execute("INSERT INTO email_outbox(id,user_id,kind,recipient,subject,body,created_at) VALUES(?,?,?,?,?,?,?)", (message_id, user_id, kind, recipient, subject[:200], body, now_iso()))
        conn.commit()
    finally:
        conn.close()
    return {"id": message_id, "kind": kind, "recipient": recipient, "subject": subject}


def list_email_outbox(user_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    conn = db.connect()
    try:
        if user_id:
            rows = conn.execute("SELECT * FROM email_outbox WHERE user_id=? ORDER BY created_at DESC LIMIT ?", (user_id, limit)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM email_outbox ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def upsert_oauth_account(user_id: str, provider: str, provider_user_id: str, email: str, profile: dict[str, Any]) -> None:
    now = now_iso()
    conn = db.connect()
    try:
        existing = conn.execute("SELECT id FROM oauth_accounts WHERE provider=? AND provider_user_id=?", (provider, provider_user_id)).fetchone()
        if existing:
            conn.execute("UPDATE oauth_accounts SET user_id=?, email=?, profile_json=?, updated_at=? WHERE id=?", (user_id, email, json.dumps(profile), now, existing["id"]))
        else:
            conn.execute("INSERT INTO oauth_accounts(id,user_id,provider,provider_user_id,email,profile_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (secrets.token_urlsafe(15), user_id, provider, provider_user_id, email, json.dumps(profile), now, now))
        conn.commit()
    finally:
        conn.close()


def get_oauth_user(provider: str, provider_user_id: str) -> dict[str, Any] | None:
    conn = db.connect()
    try:
        row = conn.execute("SELECT u.* FROM oauth_accounts o JOIN users u ON u.id=o.user_id WHERE o.provider=? AND o.provider_user_id=?", (provider, provider_user_id)).fetchone()
        return _row(row)
    finally:
        conn.close()
