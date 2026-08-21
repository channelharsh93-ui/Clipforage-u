from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .auth_context import current_user_id
from .config import DB_PATH, ensure_storage


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    ensure_storage()
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                owner_id TEXT,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'created',
                progress INTEGER NOT NULL DEFAULT 0,
                current_stage TEXT NOT NULL DEFAULT 'Waiting for video',
                original_path TEXT,
                source_type TEXT NOT NULL DEFAULT 'upload',
                source_url TEXT,
                original_filename TEXT,
                duration REAL,
                width INTEGER,
                height INTEGER,
                fps REAL,
                audio_channels INTEGER DEFAULT 0,
                processing_started_at TEXT,
                processing_finished_at TEXT,
                processing_ms REAL,
                rights_acknowledged INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS clips (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                rank INTEGER NOT NULL DEFAULT 0,
                category TEXT NOT NULL DEFAULT 'OTHER',
                score REAL NOT NULL DEFAULT 0,
                reason TEXT,
                start_sec REAL NOT NULL,
                end_sec REAL NOT NULL,
                duration REAL NOT NULL,
                transcript TEXT,
                hook TEXT,
                title TEXT,
                title_suggestions TEXT NOT NULL DEFAULT '[]',
                description TEXT,
                hashtags TEXT NOT NULL DEFAULT '[]',
                captions_enabled INTEGER NOT NULL DEFAULT 1,
                caption_style TEXT NOT NULL DEFAULT 'bold',
                caption_font_size INTEGER NOT NULL DEFAULT 42,
                caption_position TEXT NOT NULL DEFAULT 'bottom',
                hook_enabled INTEGER NOT NULL DEFAULT 0,
                hook_position TEXT NOT NULL DEFAULT 'top',
                hook_duration REAL NOT NULL DEFAULT 2.5,
                format TEXT NOT NULL DEFAULT '9:16',
                logo_path TEXT,
                logo_position TEXT NOT NULL DEFAULT 'top-right',
                logo_opacity REAL NOT NULL DEFAULT 0.85,
                intro_text TEXT NOT NULL DEFAULT '',
                outro_text TEXT NOT NULL DEFAULT '',
                intro_duration REAL NOT NULL DEFAULT 1.2,
                outro_duration REAL NOT NULL DEFAULT 1.2,
                music_path TEXT,
                music_volume REAL NOT NULL DEFAULT 0.14,
                sfx_path TEXT,
                sfx_volume REAL NOT NULL DEFAULT 0.35,
                speed REAL NOT NULL DEFAULT 1.0,
                effects TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'queued',
                video_path TEXT,
                thumbnail_path TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS render_jobs (
                id TEXT PRIMARY KEY,
                project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
                clip_id TEXT REFERENCES clips(id) ON DELETE CASCADE,
                status TEXT NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0,
                message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS social_connections (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                provider_id TEXT NOT NULL,
                account_id TEXT NOT NULL,
                account_name TEXT NOT NULL,
                token_encrypted TEXT NOT NULL,
                refresh_token_encrypted TEXT,
                expires_at TEXT,
                scopes TEXT NOT NULL DEFAULT '[]',
                metadata TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'connected',
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(provider_id, account_id)
            );

            CREATE TABLE IF NOT EXISTS oauth_states (
                state TEXT PRIMARY KEY,
                provider_id TEXT NOT NULL,
                purpose TEXT NOT NULL DEFAULT 'import',
                redirect_uri TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS publish_queue (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                clip_id TEXT NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
                platform TEXT NOT NULL,
                account_id TEXT,
                caption TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                hashtags TEXT NOT NULL DEFAULT '[]',
                thumbnail_path TEXT,
                visibility TEXT NOT NULL DEFAULT 'private',
                scheduled_at TEXT,
                status TEXT NOT NULL DEFAULT 'Ready',
                remote_id TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS content_packs (
                id TEXT PRIMARY KEY,
                clip_id TEXT NOT NULL UNIQUE REFERENCES clips(id) ON DELETE CASCADE,
                language TEXT NOT NULL DEFAULT 'en',
                tone TEXT NOT NULL DEFAULT 'casual',
                data TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS seo_scores (
                id TEXT PRIMARY KEY,
                clip_id TEXT NOT NULL UNIQUE REFERENCES clips(id) ON DELETE CASCADE,
                score REAL NOT NULL DEFAULT 0,
                data TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS usage_events (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                event_type TEXT NOT NULL,
                amount REAL NOT NULL DEFAULT 0,
                project_id TEXT,
                period TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS plan_requests (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                plan_id TEXT NOT NULL,
                contact TEXT,
                note TEXT,
                status TEXT NOT NULL DEFAULT 'local_interest',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_projects_created ON projects(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_clips_project ON clips(project_id, rank);
            CREATE INDEX IF NOT EXISTS idx_publish_queue_created ON publish_queue(created_at DESC);
            """
        )
        # Lightweight migrations for projects created by earlier MVP revisions.
        existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(clips)").fetchall()}
        if "title_suggestions" not in existing_columns:
            conn.execute("ALTER TABLE clips ADD COLUMN title_suggestions TEXT NOT NULL DEFAULT '[]'")
        if "hashtags" not in existing_columns:
            conn.execute("ALTER TABLE clips ADD COLUMN hashtags TEXT NOT NULL DEFAULT '[]'")
        project_columns = {row[1] for row in conn.execute("PRAGMA table_info(projects)").fetchall()}
        if "owner_id" not in project_columns:
            conn.execute("ALTER TABLE projects ADD COLUMN owner_id TEXT")
        if "processing_started_at" not in project_columns:
            conn.execute("ALTER TABLE projects ADD COLUMN processing_started_at TEXT")
        if "processing_finished_at" not in project_columns:
            conn.execute("ALTER TABLE projects ADD COLUMN processing_finished_at TEXT")
        if "processing_ms" not in project_columns:
            conn.execute("ALTER TABLE projects ADD COLUMN processing_ms REAL")
        plan_request_columns = {row[1] for row in conn.execute("PRAGMA table_info(plan_requests)").fetchall()}
        if "user_id" not in plan_request_columns:
            conn.execute("ALTER TABLE plan_requests ADD COLUMN user_id TEXT")
        social_columns = {row[1] for row in conn.execute("PRAGMA table_info(social_connections)").fetchall()}
        if "user_id" not in social_columns:
            conn.execute("ALTER TABLE social_connections ADD COLUMN user_id TEXT")
        publish_columns = {row[1] for row in conn.execute("PRAGMA table_info(publish_queue)").fetchall()}
        if "user_id" not in publish_columns:
            conn.execute("ALTER TABLE publish_queue ADD COLUMN user_id TEXT")
        usage_columns = {row[1] for row in conn.execute("PRAGMA table_info(usage_events)").fetchall()}
        if "user_id" not in usage_columns:
            conn.execute("ALTER TABLE usage_events ADD COLUMN user_id TEXT")
        clip_columns = {row[1] for row in conn.execute("PRAGMA table_info(clips)").fetchall()}
        if "intro_text" not in clip_columns:
            conn.execute("ALTER TABLE clips ADD COLUMN intro_text TEXT NOT NULL DEFAULT ''")
        if "outro_text" not in clip_columns:
            conn.execute("ALTER TABLE clips ADD COLUMN outro_text TEXT NOT NULL DEFAULT ''")
        if "intro_duration" not in clip_columns:
            conn.execute("ALTER TABLE clips ADD COLUMN intro_duration REAL NOT NULL DEFAULT 1.2")
        if "outro_duration" not in clip_columns:
            conn.execute("ALTER TABLE clips ADD COLUMN outro_duration REAL NOT NULL DEFAULT 1.2")
        conn.commit()
    finally:
        conn.close()


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def _rows(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def create_project(name: str, rights_acknowledged: bool, source_type: str = "upload", source_url: str | None = None, owner_id: str | None = None) -> dict[str, Any]:
    project_id = str(uuid.uuid4())
    now = now_iso()
    owner_id = owner_id or current_user_id()
    conn = connect()
    try:
        conn.execute(
            """INSERT INTO projects
            (id, owner_id, name, source_type, source_url, rights_acknowledged, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (project_id, owner_id, name.strip() or "Untitled project", source_type, source_url, int(rights_acknowledged), now, now),
        )
        conn.commit()
        return get_project(project_id)  # type: ignore[return-value]
    finally:
        conn.close()


def get_project(project_id: str) -> dict[str, Any] | None:
    conn = connect()
    try:
        user_id = current_user_id()
        if user_id:
            row = conn.execute("SELECT * FROM projects WHERE id = ? AND owner_id = ?", (project_id, user_id)).fetchone()
        else:
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return _row(row)
    finally:
        conn.close()


def list_projects(limit: int = 50) -> list[dict[str, Any]]:
    conn = connect()
    try:
        user_id = current_user_id()
        if user_id:
            rows = _rows(conn.execute("SELECT * FROM projects WHERE owner_id = ? ORDER BY created_at DESC LIMIT ?", (user_id, limit)).fetchall())
        else:
            rows = _rows(conn.execute("SELECT * FROM projects ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall())
        for item in rows:
            item["clip_count"] = conn.execute("SELECT COUNT(*) FROM clips WHERE project_id = ?", (item["id"],)).fetchone()[0]
            item["ready_count"] = conn.execute(
                "SELECT COUNT(*) FROM clips WHERE project_id = ? AND status = 'ready'", (item["id"],)
            ).fetchone()[0]
        return rows
    finally:
        conn.close()


def update_project(project_id: str, **fields: Any) -> dict[str, Any] | None:
    fields["updated_at"] = now_iso()
    allowed = {
        "name", "status", "progress", "current_stage", "original_path", "source_type", "source_url",
        "original_filename", "duration", "width", "height", "fps", "audio_channels", "processing_started_at", "processing_finished_at", "processing_ms", "error",
    }
    fields = {key: value for key, value in fields.items() if key in allowed}
    if not fields:
        return get_project(project_id)
    assignments = ", ".join(f"{key} = ?" for key in fields)
    user_id = current_user_id()
    values = list(fields.values()) + [project_id]
    conn = connect()
    try:
        if user_id:
            conn.execute(f"UPDATE projects SET {assignments} WHERE id = ? AND owner_id = ?", [*values, user_id])
        else:
            conn.execute(f"UPDATE projects SET {assignments} WHERE id = ?", values)
        conn.commit()
        return get_project(project_id)
    finally:
        conn.close()


def delete_project(project_id: str) -> None:
    conn = connect()
    try:
        user_id = current_user_id()
        if user_id:
            conn.execute("DELETE FROM projects WHERE id = ? AND owner_id = ?", (project_id, user_id))
        else:
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        conn.commit()
    finally:
        conn.close()


def create_clip(project_id: str, data: dict[str, Any]) -> dict[str, Any]:
    clip_id = str(uuid.uuid4())
    now = now_iso()
    values = {
        "id": clip_id,
        "project_id": project_id,
        "rank": data.get("rank", 0),
        "category": data.get("category", "OTHER"),
        "score": data.get("score", 0),
        "reason": data.get("reason", ""),
        "start_sec": data["start_sec"],
        "end_sec": data["end_sec"],
        "duration": data.get("duration", data["end_sec"] - data["start_sec"]),
        "transcript": json.dumps(data.get("transcript", []), ensure_ascii=False),
        "hook": data.get("hook", ""),
        "title": data.get("title", "Untitled moment"),
        "title_suggestions": json.dumps(data.get("title_suggestions", []), ensure_ascii=False),
        "description": data.get("description", ""),
        "hashtags": json.dumps(data.get("hashtags", []), ensure_ascii=False),
        "captions_enabled": int(data.get("captions_enabled", True)),
        "caption_style": data.get("caption_style", "bold"),
        "caption_font_size": data.get("caption_font_size", 42),
        "caption_position": data.get("caption_position", "bottom"),
        "hook_enabled": int(data.get("hook_enabled", False)),
        "hook_position": data.get("hook_position", "top"),
        "hook_duration": data.get("hook_duration", 2.5),
        "format": data.get("format", "9:16"),
        "logo_path": data.get("logo_path"),
        "logo_position": data.get("logo_position", "top-right"),
        "logo_opacity": data.get("logo_opacity", 0.85),
        "intro_text": data.get("intro_text", ""),
        "outro_text": data.get("outro_text", ""),
        "intro_duration": data.get("intro_duration", 1.2),
        "outro_duration": data.get("outro_duration", 1.2),
        "music_path": data.get("music_path"),
        "music_volume": data.get("music_volume", 0.14),
        "sfx_path": data.get("sfx_path"),
        "sfx_volume": data.get("sfx_volume", 0.35),
        "speed": data.get("speed", 1.0),
        "effects": json.dumps(data.get("effects", {})),
        "status": data.get("status", "queued"),
        "video_path": data.get("video_path"),
        "thumbnail_path": data.get("thumbnail_path"),
        "error": data.get("error"),
        "created_at": now,
        "updated_at": now,
    }
    columns = ", ".join(values.keys())
    placeholders = ", ".join("?" for _ in values)
    conn = connect()
    try:
        conn.execute(f"INSERT INTO clips ({columns}) VALUES ({placeholders})", list(values.values()))
        conn.commit()
        return get_clip(clip_id)  # type: ignore[return-value]
    finally:
        conn.close()


def _decode_clip(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not item:
        return None
    for key in ("captions_enabled", "hook_enabled"):
        item[key] = bool(item.get(key))
    try:
        item["transcript"] = json.loads(item.get("transcript") or "[]")
    except json.JSONDecodeError:
        item["transcript"] = []
    try:
        item["effects"] = json.loads(item.get("effects") or "{}")
    except json.JSONDecodeError:
        item["effects"] = {}
    for key in ("title_suggestions", "hashtags"):
        try:
            item[key] = json.loads(item.get(key) or "[]")
        except json.JSONDecodeError:
            item[key] = []
    return item


def get_clip(clip_id: str) -> dict[str, Any] | None:
    conn = connect()
    try:
        user_id = current_user_id()
        if user_id:
            row = conn.execute("SELECT c.* FROM clips c JOIN projects p ON p.id=c.project_id WHERE c.id = ? AND p.owner_id = ?", (clip_id, user_id)).fetchone()
        else:
            row = conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
        return _decode_clip(_row(row))
    finally:
        conn.close()


def list_clips(project_id: str) -> list[dict[str, Any]]:
    conn = connect()
    try:
        user_id = current_user_id()
        if user_id:
            rows = conn.execute("SELECT c.* FROM clips c JOIN projects p ON p.id=c.project_id WHERE c.project_id = ? AND p.owner_id = ? ORDER BY c.rank ASC, c.score DESC", (project_id, user_id)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM clips WHERE project_id = ? ORDER BY rank ASC, score DESC", (project_id,)).fetchall()
        return [_decode_clip(item) for item in _rows(rows)]  # type: ignore[list-item]
    finally:
        conn.close()


def update_clip(clip_id: str, **fields: Any) -> dict[str, Any] | None:
    fields["updated_at"] = now_iso()
    allowed = {
        "rank", "category", "score", "reason", "start_sec", "end_sec", "duration", "transcript", "hook", "title",
        "description", "title_suggestions", "hashtags", "captions_enabled", "caption_style", "caption_font_size", "caption_position", "hook_enabled",
        "hook_position", "hook_duration", "format", "logo_path", "logo_position", "logo_opacity", "music_path",
        "music_volume", "sfx_path", "sfx_volume", "speed", "effects", "intro_text", "outro_text", "intro_duration", "outro_duration", "status", "video_path", "thumbnail_path", "error",
    }
    fields = {key: value for key, value in fields.items() if key in allowed}
    if "transcript" in fields and not isinstance(fields["transcript"], str):
        fields["transcript"] = json.dumps(fields["transcript"], ensure_ascii=False)
    for key in ("title_suggestions", "hashtags"):
        if key in fields and not isinstance(fields[key], str):
            fields[key] = json.dumps(fields[key], ensure_ascii=False)
    if "effects" in fields and not isinstance(fields["effects"], str):
        fields["effects"] = json.dumps(fields["effects"])
    if "captions_enabled" in fields:
        fields["captions_enabled"] = int(bool(fields["captions_enabled"]))
    if "hook_enabled" in fields:
        fields["hook_enabled"] = int(bool(fields["hook_enabled"]))
    if not fields:
        return get_clip(clip_id)
    assignments = ", ".join(f"{key} = ?" for key in fields)
    user_id = current_user_id()
    values = list(fields.values()) + [clip_id]
    conn = connect()
    try:
        if user_id:
            conn.execute(f"UPDATE clips SET {assignments} WHERE id = ? AND project_id IN (SELECT id FROM projects WHERE owner_id = ?)", [*values, user_id])
        else:
            conn.execute(f"UPDATE clips SET {assignments} WHERE id = ?", values)
        conn.commit()
        return get_clip(clip_id)
    finally:
        conn.close()


def delete_clip(clip_id: str) -> None:
    conn = connect()
    try:
        user_id = current_user_id()
        if user_id:
            conn.execute("DELETE FROM clips WHERE id = ? AND project_id IN (SELECT id FROM projects WHERE owner_id = ?)", (clip_id, user_id))
        else:
            conn.execute("DELETE FROM clips WHERE id = ?", (clip_id,))
        conn.commit()
    finally:
        conn.close()


def create_render_job(project_id: str, clip_id: str, status: str = "queued") -> dict[str, Any]:
    job_id = str(uuid.uuid4())
    now = now_iso()
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO render_jobs (id, project_id, clip_id, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (job_id, project_id, clip_id, status, now, now),
        )
        conn.commit()
        return get_render_job(job_id)  # type: ignore[return-value]
    finally:
        conn.close()


def get_render_job(job_id: str) -> dict[str, Any] | None:
    conn = connect()
    try:
        user_id = current_user_id()
        if user_id:
            row = conn.execute("SELECT r.* FROM render_jobs r JOIN projects p ON p.id=r.project_id WHERE r.id = ? AND p.owner_id = ?", (job_id, user_id)).fetchone()
        else:
            row = conn.execute("SELECT * FROM render_jobs WHERE id = ?", (job_id,)).fetchone()
        return _row(row)
    finally:
        conn.close()


def update_render_job(job_id: str, **fields: Any) -> dict[str, Any] | None:
    fields["updated_at"] = now_iso()
    assignments = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [job_id]
    conn = connect()
    try:
        conn.execute(f"UPDATE render_jobs SET {assignments} WHERE id = ?", values)
        conn.commit()
        return get_render_job(job_id)
    finally:
        conn.close()
