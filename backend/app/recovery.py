from __future__ import annotations

from pathlib import Path

from . import db


def recover_interrupted_work() -> None:
    """Do not leave progress bars stuck forever after a server restart."""
    conn = db.connect()
    try:
        project_statuses = ("preparing", "transcribing", "detecting_scenes", "detecting_highlights", "scoring_moments", "creating_clips", "adding_captions", "generating_content", "seo_analysis")
        placeholders = ",".join("?" for _ in project_statuses)
        conn.execute(
            f"UPDATE projects SET status='failed', progress=100, current_stage='Processing interrupted', error='The local worker stopped before this project finished. You can retry it.', updated_at=? WHERE status IN ({placeholders})",
            (db.now_iso(), *project_statuses),
        )
        conn.execute(
            "UPDATE render_jobs SET status='failed', progress=100, message='The local worker stopped before this render finished.', updated_at=? WHERE status IN ('queued','rendering')",
            (db.now_iso(),),
        )
        conn.commit()
    finally:
        conn.close()


def clear_project_clips(project_id: str) -> None:
    """Remove previous generated outputs before a deliberate project retry."""
    conn = db.connect()
    try:
        rows = conn.execute("SELECT video_path, thumbnail_path FROM clips WHERE project_id = ?", (project_id,)).fetchall()
        conn.execute("DELETE FROM clips WHERE project_id = ?", (project_id,))
        conn.commit()
        for row in rows:
            for key in ("video_path", "thumbnail_path"):
                if row[key]:
                    Path(row[key]).unlink(missing_ok=True)
    finally:
        conn.close()
