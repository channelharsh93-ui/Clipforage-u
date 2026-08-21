from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import MAX_STORAGE_GB, RETENTION_DAYS, STORAGE_ROOT


def _size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def storage_status() -> dict[str, Any]:
    used = _size_bytes(STORAGE_ROOT)
    disk = shutil.disk_usage(STORAGE_ROOT)
    limit = int(MAX_STORAGE_GB * 1024 * 1024 * 1024) if MAX_STORAGE_GB > 0 else None
    return {
        "used_bytes": used,
        "used_mb": round(used / 1024 / 1024, 2),
        "used_gb": round(used / 1024 / 1024 / 1024, 3),
        "limit_gb": MAX_STORAGE_GB if MAX_STORAGE_GB > 0 else None,
        "limit_reached": bool(limit and used >= limit),
        "disk_free_gb": round(disk.free / 1024 / 1024 / 1024, 2),
        "retention_days": RETENTION_DAYS,
        "mode": "local-filesystem",
    }


def ensure_capacity(extra_bytes: int = 0) -> None:
    if MAX_STORAGE_GB <= 0:
        return
    current = _size_bytes(STORAGE_ROOT)
    limit = int(MAX_STORAGE_GB * 1024 * 1024 * 1024)
    if current + max(0, extra_bytes) > limit:
        raise RuntimeError(f"Local storage limit reached ({MAX_STORAGE_GB:g} GB). Delete older projects or increase MAX_STORAGE_GB.")


def cleanup_expired_projects() -> dict[str, Any]:
    """Optional local cleanup. Disabled unless RETENTION_DAYS is explicitly positive."""
    if RETENTION_DAYS <= 0:
        return {"deleted": 0, "enabled": False, "message": "Automatic retention cleanup is disabled."}
    from . import db
    import shutil as _shutil

    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    deleted = 0
    for project in db.list_projects(limit=10000):
        if project.get("status") not in {"finished", "failed"}:
            continue
        try:
            updated = datetime.fromisoformat(str(project.get("updated_at")).replace("Z", "+00:00"))
        except Exception:
            continue
        if updated < cutoff:
            _shutil.rmtree(STORAGE_ROOT / "projects" / project["id"], ignore_errors=True)
            db.delete_project(project["id"])
            deleted += 1
    return {"deleted": deleted, "enabled": True, "retention_days": RETENTION_DAYS}
