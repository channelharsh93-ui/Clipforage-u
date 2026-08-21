from __future__ import annotations

import json
import time
import traceback
from pathlib import Path
from typing import Any, Callable

from .. import content_db, db
from ..auth_context import reset_context, set_context
from ..config import project_root
from ..usage_service import record as record_usage
from ..user_settings import get_user_settings
from ..plans import current_plan
from .analysis import detect_scenes, generate_candidates, score_candidates
from .caption_ass import write_caption_ass
from .content_generator import generate_content_pack
from .ffmpeg import audio_windows, extract_audio, make_thumbnail, probe_video, render_clip, write_branding_srt
from .transcription import transcribe


ProgressCallback = Callable[[str, int, str], None]


def _set_progress(project_id: str, status: str, progress: int, stage: str, callback: ProgressCallback | None = None, **extra: Any) -> None:
    db.update_project(project_id, status=status, progress=max(0, min(100, progress)), current_stage=stage, **extra)
    if callback:
        callback(status, progress, stage)


def process_project(project_id: str, callback: ProgressCallback | None = None, clip_limit: int | None = None) -> None:
    project = db.get_project(project_id)
    if not project or not project.get("original_path"):
        return
    started_at = time.perf_counter()
    db.update_project(project_id, processing_started_at=db.now_iso(), processing_finished_at=None, processing_ms=None)
    try:
        source = Path(project["original_path"])
        if not source.exists():
            raise RuntimeError("The uploaded video is no longer available.")
        root = project_root(project_id)
        user_settings = get_user_settings()
        analysis_dir = root / "analysis"
        clips_dir = root / "clips"
        analysis_dir.mkdir(parents=True, exist_ok=True)
        clips_dir.mkdir(parents=True, exist_ok=True)

        _set_progress(project_id, "preparing", 5, "Preparing video", callback)
        metadata = probe_video(source)
        db.update_project(project_id, **metadata)
        record_usage("projects", 1, project_id=project_id)
        record_usage("source_minutes", float(metadata.get("duration") or 0) / 60, project_id=project_id)

        audio_path = analysis_dir / "audio.wav"
        audio_features: list[dict[str, float]] = []
        if metadata.get("has_audio"):
            _set_progress(project_id, "transcribing", 13, "Extracting audio", callback)
            extract_audio(source, audio_path)
            audio_features = audio_windows(audio_path)
        else:
            _set_progress(project_id, "transcribing", 13, "No audio track detected", callback)

        _set_progress(project_id, "transcribing", 20, "Transcribing with local Whisper", callback)
        transcript_payload = transcribe(audio_path) if audio_path.exists() else {
            "provider": "none", "segments": [], "notice": "No audio track was detected.", "word_timestamps": False
        }
        transcript = transcript_payload.get("segments", [])
        (analysis_dir / "transcript.json").write_text(json.dumps(transcript_payload, indent=2, ensure_ascii=False), encoding="utf-8")

        _set_progress(project_id, "detecting_scenes", 36, "Detecting scene changes", callback)
        scenes, cuts = detect_scenes(
            source, float(metadata.get("duration") or 0), float(metadata.get("fps") or 30)
        )
        (analysis_dir / "scenes.json").write_text(json.dumps({"scenes": scenes, "cuts": cuts}, indent=2), encoding="utf-8")

        _set_progress(project_id, "detecting_highlights", 52, "Finding candidate moments", callback)
        candidates = generate_candidates(float(metadata.get("duration") or 0), transcript, scenes, audio_features, cuts)
        _set_progress(project_id, "scoring_moments", 64, f"Ranking {len(candidates)} candidate segments", callback)
        highlights = score_candidates(candidates, transcript, scenes, audio_features, cuts)
        plan_clip_limit = int(current_plan()["limits"]["clips_per_project"])
        effective_clip_limit = max(1, min(plan_clip_limit, int(clip_limit or plan_clip_limit)))
        highlights = highlights[:effective_clip_limit]
        (analysis_dir / "highlights.json").write_text(json.dumps({"highlights": highlights}, indent=2, ensure_ascii=False), encoding="utf-8")

        _set_progress(project_id, "creating_clips", 72, f"Creating {len(highlights)} clips", callback)
        for item in highlights:
            clip = db.create_clip(project_id, {
                "rank": item["rank"], "category": item["category"], "score": item["score"], "reason": item["reason"],
                "start_sec": item["start"], "end_sec": item["end"], "duration": item["duration"], "transcript": item["transcript"],
                "hook": item["hook"], "title": item["title"], "title_suggestions": item.get("title_suggestions", []), "description": item["description"], "hashtags": item.get("hashtags", []), "format": user_settings["default_aspect"], "caption_style": user_settings["caption_style"], "caption_position": user_settings["caption_position"], "status": "rendering",
            })
            record_usage("clips", 1, metadata={"clip_id": clip["id"], "project_id": project_id})
            try:
                render_clip_for_record(clip["id"], initial=True)
            except Exception as exc:
                db.update_clip(clip["id"], status="failed", error=str(exc))

        _set_progress(project_id, "adding_captions", 90, "Adding synchronized captions", callback)
        _set_progress(project_id, "generating_content", 94, "Generating local content packs", callback)
        for clip_record in db.list_clips(project_id):
            if clip_record.get("status") != "ready":
                continue
            pack = generate_content_pack(clip_record, language=user_settings["language"], tone=user_settings["tone"])
            pack["hashtags"]["all"] = pack.get("hashtags", {}).get("all", [])[: int(user_settings["hashtag_count"])]
            content_db.upsert_content_pack(clip_record["id"], pack, language=user_settings["language"], tone=user_settings["tone"])
        _set_progress(project_id, "seo_analysis", 97, "Scoring titles, descriptions, keywords, and hashtags", callback)
        db.update_project(project_id, processing_finished_at=db.now_iso(), processing_ms=round((time.perf_counter() - started_at) * 1000, 1))
        _set_progress(project_id, "finished", 100, "Finished", callback)
    except Exception as exc:
        db.update_project(project_id, status="failed", progress=100, current_stage="Processing failed", error=str(exc), processing_finished_at=db.now_iso(), processing_ms=round((time.perf_counter() - started_at) * 1000, 1))
        if callback:
            callback("failed", 100, str(exc))
        traceback.print_exc()


def render_clip_for_record(clip_id: str, job_id: str | None = None, initial: bool = False) -> dict[str, Any]:
    clip = db.get_clip(clip_id)
    if not clip:
        raise RuntimeError("Clip not found")
    project = db.get_project(clip["project_id"])
    if not project or not project.get("original_path"):
        raise RuntimeError("Source video not found")
    root = project_root(project["id"])
    output_dir = root / "clips"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{clip_id}.mp4"
    thumbnail = output_dir / f"{clip_id}.jpg"
    caption_path = None
    if clip.get("captions_enabled") and clip.get("transcript"):
        caption_path = output_dir / f"{clip_id}.ass"
        caption_path = write_caption_ass(clip["transcript"], float(clip["start_sec"]), float(clip["end_sec"]), caption_path, style=clip.get("caption_style", "bold"), position=clip.get("caption_position", "bottom"), font_size=int(clip.get("caption_font_size", 42)))
    branding_path = output_dir / f"{clip_id}.branding.srt"
    branding_path = write_branding_srt(clip.get("intro_text", ""), clip.get("outro_text", ""), float(clip["duration"]), float(clip.get("intro_duration", 1.2)), float(clip.get("outro_duration", 1.2)), branding_path)
    hook_path = None
    if clip.get("hook_enabled") and clip.get("hook"):
        hook_path = output_dir / f"{clip_id}.hook.txt"
        hook_path.write_text(str(clip["hook"]), encoding="utf-8")
    logo_path = clip.get("logo_path")
    music_path = clip.get("music_path")
    sfx_path = clip.get("sfx_path")
    if logo_path and not Path(logo_path).exists():
        logo_path = None
    if music_path and not Path(music_path).exists():
        music_path = None
    if sfx_path and not Path(sfx_path).exists():
        sfx_path = None

    if job_id:
        db.update_render_job(job_id, status="rendering", progress=20, message="Rendering video")
    result = render_clip(
        source_path=project["original_path"], output_path=output,
        start_sec=float(clip["start_sec"]), end_sec=float(clip["end_sec"]),
        aspect=clip.get("format", "9:16"), captions_path=caption_path, branding_srt_path=branding_path,
        caption_style=clip.get("caption_style", "bold"), caption_position=clip.get("caption_position", "bottom"),
        caption_font_size=int(clip.get("caption_font_size", 42)), hook_path=hook_path,
        hook_position=clip.get("hook_position", "top"), hook_duration=float(clip.get("hook_duration", 2.5)), logo_path=logo_path,
        logo_position=clip.get("logo_position", "top-right"), logo_opacity=float(clip.get("logo_opacity", 0.85)),
        music_path=music_path, music_volume=float(clip.get("music_volume", 0.14)),
        sfx_path=sfx_path, sfx_volume=float(clip.get("sfx_volume", 0.35)),
        speed=float(clip.get("speed", 1.0)), effects=clip.get("effects") or {},
    )
    make_thumbnail(output, thumbnail)
    updated = db.update_clip(clip_id, status="ready", video_path=str(output), thumbnail_path=str(thumbnail), error=None)
    if job_id:
        db.update_render_job(job_id, status="finished", progress=100, message="Video ready")
    return {"clip": updated, "render": result}


def process_project_job(project_id: str, clip_limit: int | None, owner_id: str | None) -> None:
    tokens = set_context(owner_id, None)
    try:
        process_project(project_id, None, clip_limit)
    finally:
        reset_context(tokens)


def render_clip_async(clip_id: str, job_id: str) -> None:
    try:
        render_clip_for_record(clip_id, job_id=job_id)
    except Exception as exc:
        db.update_clip(clip_id, status="failed", error=str(exc))
        db.update_render_job(job_id, status="failed", progress=100, message=str(exc))
        traceback.print_exc()


def render_clip_job(clip_id: str, job_id: str, owner_id: str | None) -> None:
    tokens = set_context(owner_id, None)
    try:
        render_clip_async(clip_id, job_id)
    finally:
        reset_context(tokens)
