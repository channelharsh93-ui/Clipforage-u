from __future__ import annotations

import json
import uuid
from typing import Any

from . import db


def _now() -> str:
    return db.now_iso()


def _decode(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    try:
        row["data"] = json.loads(row.get("data") or "{}")
    except json.JSONDecodeError:
        row["data"] = {}
    return row


def upsert_content_pack(clip_id: str, data: dict[str, Any], language: str = "en", tone: str = "casual") -> dict[str, Any]:
    now = _now()
    pack_id = str(uuid.uuid4())
    conn = db.connect()
    try:
        conn.execute(
            """INSERT INTO content_packs (id, clip_id, language, tone, data, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(clip_id) DO UPDATE SET language=excluded.language, tone=excluded.tone, data=excluded.data, updated_at=excluded.updated_at""",
            (pack_id, clip_id, language, tone, json.dumps(data, ensure_ascii=False), now, now),
        )
        seo = data.get("seo", {}) if isinstance(data, dict) else {}
        conn.execute(
            """INSERT INTO seo_scores (id, clip_id, score, data, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(clip_id) DO UPDATE SET score=excluded.score, data=excluded.data, updated_at=excluded.updated_at""",
            (str(uuid.uuid4()), clip_id, float(seo.get("score", 0)), json.dumps(seo, ensure_ascii=False), now, now),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM content_packs WHERE clip_id = ?", (clip_id,)).fetchone()
        return _decode(dict(row))  # type: ignore[return-value]
    finally:
        conn.close()


def get_content_pack(clip_id: str) -> dict[str, Any] | None:
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM content_packs WHERE clip_id = ?", (clip_id,)).fetchone()
        return _decode(dict(row)) if row else None
    finally:
        conn.close()


def list_content_packs(project_id: str) -> list[dict[str, Any]]:
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT cp.* FROM content_packs cp JOIN clips c ON c.id = cp.clip_id WHERE c.project_id = ? ORDER BY c.rank ASC",
            (project_id,),
        ).fetchall()
        return [_decode(dict(row)) for row in rows]  # type: ignore[list-item]
    finally:
        conn.close()
