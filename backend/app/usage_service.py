from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from . import db
from .auth_context import current_user_id
from .plans import PLANS, current_plan_id


def _period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def record(event_type: str, amount: float, project_id: str | None = None, metadata: dict[str, Any] | None = None, user_id: str | None = None) -> None:
    conn = db.connect()
    scoped_user_id = user_id or current_user_id()
    try:
        if project_id:
            duplicate_query = "SELECT 1 FROM usage_events WHERE event_type=? AND project_id=?"
            duplicate_values: tuple[Any, ...] = (event_type, project_id)
            if scoped_user_id:
                duplicate_query += " AND user_id=?"
                duplicate_values = (event_type, project_id, scoped_user_id)
            if conn.execute(duplicate_query, duplicate_values).fetchone():
                return
        conn.execute(
            "INSERT INTO usage_events(id,user_id,event_type,amount,project_id,period,metadata,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), scoped_user_id, event_type, float(amount), project_id, _period(), json.dumps(metadata or {}), db.now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def usage() -> dict[str, Any]:
    period = _period()
    day_start = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn = db.connect()
    scoped_user_id = current_user_id()
    try:
        if scoped_user_id:
            rows = conn.execute("SELECT event_type, SUM(amount) AS total FROM usage_events WHERE period=? AND user_id=? GROUP BY event_type", (period, scoped_user_id)).fetchall()
            daily_clips_row = conn.execute("SELECT COALESCE(SUM(amount), 0) AS total FROM usage_events WHERE event_type='clips' AND created_at >= ? AND user_id=?", (day_start, scoped_user_id)).fetchone()
            daily_jobs_row = conn.execute("SELECT COALESCE(SUM(amount), 0) AS total FROM usage_events WHERE event_type='processing_jobs' AND created_at >= ? AND user_id=?", (day_start, scoped_user_id)).fetchone()
        else:
            rows = conn.execute("SELECT event_type, SUM(amount) AS total FROM usage_events WHERE period=? GROUP BY event_type", (period,)).fetchall()
            daily_clips_row = conn.execute("SELECT COALESCE(SUM(amount), 0) AS total FROM usage_events WHERE event_type='clips' AND created_at >= ?", (day_start,)).fetchone()
            daily_jobs_row = conn.execute("SELECT COALESCE(SUM(amount), 0) AS total FROM usage_events WHERE event_type='processing_jobs' AND created_at >= ?", (day_start,)).fetchone()
    finally:
        conn.close()
    totals = {row["event_type"]: float(row["total"] or 0) for row in rows}
    daily_clips = float((daily_clips_row or {"total": 0})["total"] or 0)
    daily_processing_jobs = float((daily_jobs_row or {"total": 0})["total"] or 0)
    plan_id = current_plan_id()
    limits = PLANS[plan_id]["limits"]
    return {
        "period": period,
        "plan_id": plan_id,
        "source_minutes": round(totals.get("source_minutes", 0), 1),
        "projects": int(totals.get("projects", 0)),
        "clips": int(totals.get("clips", 0)),
        "daily_clips": int(daily_clips),
        "daily_processing_jobs": int(daily_processing_jobs),
        "limits": limits,
        "remaining": {
            "source_minutes": max(0, limits["monthly_source_minutes"] - totals.get("source_minutes", 0)),
            "projects": max(0, limits["projects"] - totals.get("projects", 0)),
            "daily_clips": max(0, limits["daily_clips"] - daily_clips),
            "daily_processing_jobs": max(0, limits.get("daily_processing_jobs", 10_000) - daily_processing_jobs),
        },
        "note": "Usage is measured locally. Free local processing remains available without a payment provider.",
    }


def available_daily_clips(requested: int) -> int:
    meter = usage()
    return max(0, min(int(requested), int(meter["remaining"]["daily_clips"])))


def available_daily_jobs(requested: int = 1) -> int:
    meter = usage()
    return max(0, min(int(requested), int(meter["remaining"].get("daily_processing_jobs", requested))))


def plan_interest(plan_id: str, contact: str = "", note: str = "") -> dict[str, Any]:
    from .plans import PLANS
    if plan_id not in PLANS or plan_id == "free":
        raise ValueError("Choose a paid plan to request access.")
    request_id = str(uuid.uuid4())
    conn = db.connect()
    try:
        conn.execute("INSERT INTO plan_requests(id,user_id,plan_id,contact,note,created_at) VALUES(?,?,?,?,?,?)", (request_id, current_user_id(), plan_id, contact[:200], note[:500], db.now_iso()))
        conn.commit()
    finally:
        conn.close()
    return {"id": request_id, "plan_id": plan_id, "status": "local_interest", "message": "Interest saved locally. No payment was taken and no external service was contacted."}
