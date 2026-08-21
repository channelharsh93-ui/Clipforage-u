from __future__ import annotations

import json
import uuid
from typing import Any

from . import db
from .auth_context import current_user_id


def _now() -> str:
    return db.now_iso()


def create_oauth_state(provider_id: str, purpose: str, redirect_uri: str, state: str) -> None:
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO oauth_states (state, provider_id, purpose, redirect_uri, created_at) VALUES (?, ?, ?, ?, ?)",
            (state, provider_id, purpose, redirect_uri, _now()),
        )
        conn.commit()
    finally:
        conn.close()


def consume_oauth_state(state: str) -> dict[str, Any] | None:
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM oauth_states WHERE state = ?", (state,)).fetchone()
        conn.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
        conn.commit()
        return dict(row) if row else None
    finally:
        conn.close()


def save_connection(
    provider_id: str,
    account_id: str,
    account_name: str,
    token_encrypted: str,
    refresh_token_encrypted: str | None,
    expires_at: str | None,
    scopes: list[str],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    connection_id = str(uuid.uuid4())
    now = _now()
    owner_id = current_user_id()
    conn = db.connect()
    try:
        conn.execute(
            """INSERT INTO social_connections
            (id, user_id, provider_id, account_id, account_name, token_encrypted, refresh_token_encrypted, expires_at, scopes, metadata, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'connected', ?, ?)
            ON CONFLICT(provider_id, account_id) DO UPDATE SET
              user_id=excluded.user_id,
              account_name=excluded.account_name,
              token_encrypted=excluded.token_encrypted,
              refresh_token_encrypted=excluded.refresh_token_encrypted,
              expires_at=excluded.expires_at,
              scopes=excluded.scopes,
              metadata=excluded.metadata,
              status='connected',
              error=NULL,
              updated_at=excluded.updated_at""",
            (
                connection_id, owner_id, provider_id, account_id, account_name, token_encrypted, refresh_token_encrypted,
                expires_at, json.dumps(scopes), json.dumps(metadata or {}), now, now,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM social_connections WHERE provider_id = ? AND account_id = ? AND (user_id = ? OR ? IS NULL)", (provider_id, account_id, owner_id, owner_id)
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def list_connections(provider_id: str | None = None) -> list[dict[str, Any]]:
    conn = db.connect()
    owner_id = current_user_id()
    try:
        if provider_id and owner_id:
            rows = conn.execute("SELECT * FROM social_connections WHERE provider_id = ? AND user_id = ? ORDER BY updated_at DESC", (provider_id, owner_id)).fetchall()
        elif provider_id:
            rows = conn.execute("SELECT * FROM social_connections WHERE provider_id = ? ORDER BY updated_at DESC", (provider_id,)).fetchall()
        elif owner_id:
            rows = conn.execute("SELECT * FROM social_connections WHERE user_id = ? ORDER BY updated_at DESC", (owner_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM social_connections ORDER BY updated_at DESC").fetchall()
        return [_public_connection(dict(row)) for row in rows]
    finally:
        conn.close()


def get_connection(connection_id: str) -> dict[str, Any] | None:
    conn = db.connect()
    owner_id = current_user_id()
    try:
        if owner_id:
            row = conn.execute("SELECT * FROM social_connections WHERE id = ? AND user_id = ?", (connection_id, owner_id)).fetchone()
        else:
            row = conn.execute("SELECT * FROM social_connections WHERE id = ?", (connection_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_connection_for_account(provider_id: str, account_id: str) -> dict[str, Any] | None:
    conn = db.connect()
    owner_id = current_user_id()
    try:
        if owner_id:
            row = conn.execute("SELECT * FROM social_connections WHERE provider_id = ? AND account_id = ? AND user_id = ?", (provider_id, account_id, owner_id)).fetchone()
        else:
            row = conn.execute("SELECT * FROM social_connections WHERE provider_id = ? AND account_id = ?", (provider_id, account_id)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def delete_connection(connection_id: str) -> None:
    conn = db.connect()
    owner_id = current_user_id()
    try:
        if owner_id:
            conn.execute("DELETE FROM social_connections WHERE id = ? AND user_id = ?", (connection_id, owner_id))
        else:
            conn.execute("DELETE FROM social_connections WHERE id = ?", (connection_id,))
        conn.commit()
    finally:
        conn.close()


def mark_connection_error(connection_id: str, error: str) -> None:
    conn = db.connect()
    owner_id = current_user_id()
    try:
        if owner_id:
            conn.execute("UPDATE social_connections SET status='error', error=?, updated_at=? WHERE id=? AND user_id=?", (error[:1000], _now(), connection_id, owner_id))
        else:
            conn.execute("UPDATE social_connections SET status='error', error=?, updated_at=? WHERE id=?", (error[:1000], _now(), connection_id))
        conn.commit()
    finally:
        conn.close()


def decryptable_connection(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    try:
        result["scopes"] = json.loads(result.get("scopes") or "[]")
    except json.JSONDecodeError:
        result["scopes"] = []
    try:
        result["metadata"] = json.loads(result.get("metadata") or "{}")
    except json.JSONDecodeError:
        result["metadata"] = {}
    return result


def _public_connection(row: dict[str, Any]) -> dict[str, Any]:
    result = decryptable_connection(row)
    result.pop("token_encrypted", None)
    result.pop("refresh_token_encrypted", None)
    return result


def get_setting(key: str, default: Any = None) -> Any:
    conn = db.connect()
    try:
        row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return row["value"]
    finally:
        conn.close()


def set_setting(key: str, value: Any) -> None:
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO app_settings(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, json.dumps(value), _now()),
        )
        conn.commit()
    finally:
        conn.close()


def create_publish_item(
    clip_id: str, platform: str, account_id: str | None, caption: str, title: str,
    hashtags: list[str], thumbnail_path: str | None, visibility: str, scheduled_at: str | None,
) -> dict[str, Any]:
    item_id = str(uuid.uuid4())
    now = _now()
    owner_id = current_user_id()
    conn = db.connect()
    try:
        conn.execute(
            """INSERT INTO publish_queue
            (id,user_id,clip_id,platform,account_id,caption,title,hashtags,thumbnail_path,visibility,scheduled_at,status,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?, 'Ready',?,?)""",
            (item_id, owner_id, clip_id, platform, account_id, caption, title, json.dumps(hashtags), thumbnail_path, visibility, scheduled_at, now, now),
        )
        conn.commit()
        return get_publish_item(item_id)  # type: ignore[return-value]
    finally:
        conn.close()


def _public_publish(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    try:
        result["hashtags"] = json.loads(result.get("hashtags") or "[]")
    except json.JSONDecodeError:
        result["hashtags"] = []
    return result


def get_publish_item(item_id: str) -> dict[str, Any] | None:
    conn = db.connect()
    owner_id = current_user_id()
    try:
        if owner_id:
            row = conn.execute("SELECT * FROM publish_queue WHERE id = ? AND user_id = ?", (item_id, owner_id)).fetchone()
        else:
            row = conn.execute("SELECT * FROM publish_queue WHERE id = ?", (item_id,)).fetchone()
        return _public_publish(dict(row)) if row else None
    finally:
        conn.close()


def list_publish_items(limit: int = 100) -> list[dict[str, Any]]:
    conn = db.connect()
    owner_id = current_user_id()
    try:
        if owner_id:
            rows = conn.execute("SELECT * FROM publish_queue WHERE user_id = ? ORDER BY created_at DESC LIMIT ?", (owner_id, limit)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM publish_queue ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [_public_publish(dict(row)) for row in rows]
    finally:
        conn.close()


def update_publish_item(item_id: str, **fields: Any) -> dict[str, Any] | None:
    fields["updated_at"] = _now()
    allowed = {"status", "remote_id", "error", "scheduled_at", "caption", "title", "hashtags", "thumbnail_path", "visibility"}
    fields = {key: value for key, value in fields.items() if key in allowed}
    if "hashtags" in fields and not isinstance(fields["hashtags"], str):
        fields["hashtags"] = json.dumps(fields["hashtags"])
    if not fields:
        return get_publish_item(item_id)
    assignments = ", ".join(f"{key}=?" for key in fields)
    owner_id = current_user_id()
    values = list(fields.values()) + [item_id]
    conn = db.connect()
    try:
        if owner_id:
            conn.execute(f"UPDATE publish_queue SET {assignments} WHERE id=? AND user_id=?", [*values, owner_id])
        else:
            conn.execute(f"UPDATE publish_queue SET {assignments} WHERE id=?", values)
        conn.commit()
        return get_publish_item(item_id)
    finally:
        conn.close()


def delete_publish_item(item_id: str) -> None:
    conn = db.connect()
    owner_id = current_user_id()
    try:
        if owner_id:
            conn.execute("DELETE FROM publish_queue WHERE id = ? AND user_id = ?", (item_id, owner_id))
        else:
            conn.execute("DELETE FROM publish_queue WHERE id = ?", (item_id,))
        conn.commit()
    finally:
        conn.close()
