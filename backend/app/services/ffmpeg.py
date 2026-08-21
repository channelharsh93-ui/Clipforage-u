from __future__ import annotations

import re
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Any


class FFmpegError(RuntimeError):
    pass


def _binary(name: str) -> str:
    configured = shutil.which(name)
    if configured:
        return configured
    if name == "ffmpeg":
        try:
            import imageio_ffmpeg  # type: ignore

            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass
    return name


def ffmpeg_path() -> str:
    return _binary("ffmpeg")


def run_ffmpeg(args: list[str], timeout: int = 600, check: bool = True) -> subprocess.CompletedProcess[str]:
    command = [ffmpeg_path(), "-hide_banner", "-loglevel", "error", *args]
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "FFmpeg failed")[-4000:]
        raise FFmpegError(detail)
    return result


def probe_video(path: str | Path) -> dict[str, Any]:
    """Use OpenCV for portable video metadata and FFmpeg output for audio presence."""
    import cv2  # type: ignore

    source = str(path)
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise FFmpegError("The file could not be opened as a video.")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    cap.release()
    duration = (frames / fps) if fps > 0 and frames > 0 else 0.0

    inspect = subprocess.run(
        [ffmpeg_path(), "-hide_banner", "-i", source], capture_output=True, text=True, timeout=60
    )
    probe_text = (inspect.stderr or "")
    has_audio = bool(re.search(r"Audio:", probe_text, re.IGNORECASE))
    audio_channels = 1 if has_audio else 0
    channel_match = re.search(r"Audio:.*?(mono|stereo|([1-9])\s+channels)", probe_text, re.IGNORECASE)
    if channel_match and channel_match.group(2):
        audio_channels = int(channel_match.group(2))
    if duration <= 0:
        duration_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", probe_text)
        if duration_match:
            duration = int(duration_match.group(1)) * 3600 + int(duration_match.group(2)) * 60 + float(duration_match.group(3))
    return {
        "duration": round(max(duration, 0.0), 3),
        "width": width,
        "height": height,
        "fps": round(fps, 3),
        "audio_channels": audio_channels,
        "has_audio": has_audio,
    }


def extract_audio(video_path: str | Path, output_path: str | Path) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg([
        "-y", "-i", str(video_path), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(output)
    ], timeout=300)
    return output


def audio_windows(wav_path: str | Path, window_sec: float = 0.5) -> list[dict[str, float]]:
    """Return inexpensive RMS audio features for highlight scoring."""
    try:
        with wave.open(str(wav_path), "rb") as audio:
            rate = audio.getframerate()
            frames = audio.readframes(audio.getnframes())
            channels = audio.getnchannels()
            sample_width = audio.getsampwidth()
        import numpy as np  # type: ignore

        if sample_width != 2:
            return []
        samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32)
        if channels > 1:
            samples = samples.reshape(-1, channels).mean(axis=1)
        block = max(1, int(rate * window_sec))
        output: list[dict[str, float]] = []
        for start in range(0, len(samples), block):
            chunk = samples[start : start + block]
            if len(chunk) == 0:
                continue
            rms = float(np.sqrt(np.mean(np.square(chunk))) / 32768.0)
            peak = float(np.max(np.abs(chunk)) / 32768.0)
            output.append({"start": start / rate, "end": (start + len(chunk)) / rate, "rms": rms, "peak": peak})
        if output:
            values = sorted(item["rms"] for item in output)
            median = values[len(values) // 2] or 0.001
            for item in output:
                item["relative"] = min(2.5, item["rms"] / median)
        return output
    except Exception:
        return []


def _filter_path(path: str | Path) -> str:
    # FFmpeg filter paths use ':' as a separator. Linux paths do not normally contain it,
    # but escaping makes this safe for Windows-like paths too.
    return str(path).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def _drawtext_path(path: str | Path) -> str:
    return str(path).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def detect_focus_x(video_path: str | Path, start_sec: float = 0.0, end_sec: float | None = None) -> float:
    """Find an approximate face-centered horizontal focus point with OpenCV.

    This is intentionally conservative: when no face is found, the caller receives 0.5
    and FFmpeg performs a safe center crop rather than inventing a tracking result.
    """
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return 0.5
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration = total_frames / fps if fps and total_frames else 0.0
        end = min(duration or (start_sec + 20), end_sec or (start_sec + 20))
        times = np.linspace(max(0.0, start_sec), max(start_sec + 0.1, end), 6)
        classifier = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        points: list[tuple[float, float]] = []
        for timestamp in times:
            cap.set(cv2.CAP_PROP_POS_MSEC, float(timestamp) * 1000)
            ok, frame = cap.read()
            if not ok:
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = classifier.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(32, 32))
            frame_width = max(1, frame.shape[1])
            for x, y, width, height in faces[:4]:
                area = float(width * height)
                points.append(((x + width / 2) / frame_width, area))
        cap.release()
        if not points:
            return 0.5
        total_area = sum(area for _, area in points) or 1.0
        return max(0.08, min(0.92, sum(point * area for point, area in points) / total_area))
    except Exception:
        return 0.5


def _aspect_filter(aspect: str, focus_x: float = 0.5) -> tuple[str, tuple[int, int]]:
    sizes = {"9:16": (1080, 1920), "1:1": (1080, 1080), "16:9": (1920, 1080), "4:5": (1080, 1350)}
    size = sizes.get(aspect, sizes["9:16"])
    width, height = size
    focus = max(0.08, min(0.92, float(focus_x)))
    # Scaling to the target height before cropping keeps faces/objects from being stretched.
    if aspect == "9:16":
        return f"scale=-2:{height},crop={width}:{height}:x=(iw-{width})*{focus:.3f}:y=0", size
    if aspect == "4:5":
        return f"scale=-2:{height},crop={width}:{height}:x=(iw-{width})*{focus:.3f}:y=0", size
    return f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}:x=(iw-{width})*{focus:.3f}:y=(ih-{height})/2", size


def _srt_timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    whole = int(seconds)
    millis = int(round((seconds - whole) * 1000))
    if millis >= 1000:
        whole += 1
        millis = 0
    hours, remainder = divmod(whole, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_caption_srt(transcript: list[dict[str, Any]], clip_start: float, clip_end: float, output_path: str | Path, max_words: int = 7) -> Path | None:
    cues: list[tuple[float, float, str]] = []
    for segment in transcript:
        start = max(float(segment.get("start", 0)), clip_start) - clip_start
        end = min(float(segment.get("end", 0)), clip_end) - clip_start
        text = " ".join(str(segment.get("text", "")).split())
        if end <= start or not text:
            continue
        words = text.split()
        if len(words) <= max_words:
            cues.append((start, end, text))
            continue
        # Split long transcript segments while retaining approximate word timing.
        slice_duration = (end - start) / max(1, len(words))
        for index in range(0, len(words), max_words):
            group = words[index : index + max_words]
            group_start = start + index * slice_duration
            group_end = min(end, start + (index + len(group)) * slice_duration)
            cues.append((group_start, group_end, " ".join(group)))
    if not cues:
        return None
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for index, (start, end, text) in enumerate(cues, 1):
            handle.write(f"{index}\n{_srt_timestamp(start)} --> {_srt_timestamp(end)}\n{text}\n\n")
    return output


def write_branding_srt(intro_text: str, outro_text: str, duration: float, intro_duration: float, outro_duration: float, output_path: str | Path) -> Path | None:
    cues: list[str] = []
    if intro_text.strip():
        cues.append(f"1\n{_srt_timestamp(0)} --> {_srt_timestamp(min(duration, intro_duration))}\n{intro_text.strip()[:120]}\n")
    if outro_text.strip():
        start = max(0.0, duration - outro_duration)
        index = 2 if intro_text.strip() else 1
        cues.append(f"{index}\n{_srt_timestamp(start)} --> {_srt_timestamp(duration)}\n{outro_text.strip()[:120]}\n")
    if not cues:
        return None
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(cues), encoding="utf-8")
    return output


def _caption_style(style: str, position: str, font_size: int) -> str:
    alignment = 8 if position == "top" else 5 if position == "middle" else 2
    presets = {
        "clean": "FontName=Arial,PrimaryColour=&H00FFFFFF,OutlineColour=&H99000000,BorderStyle=1,Outline=2",
        "bold": "FontName=Arial,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=3,Outline=2,Bold=1",
        "creator": "FontName=Arial,PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,BorderStyle=3,Outline=2,Bold=1",
        "podcast": "FontName=Arial,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=3,Outline=3,Bold=1",
        "minimal": "FontName=Arial,PrimaryColour=&H00FFFFFF,OutlineColour=&H99000000,BorderStyle=1,Outline=1",
        "high-energy": "FontName=Arial,PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,BorderStyle=3,Outline=3,Bold=1",
    }
    return f"{presets.get(style, presets['bold'])},FontSize={max(18, min(72, int(font_size)))},Alignment={alignment},MarginV=100"


def render_clip(
    source_path: str | Path,
    output_path: str | Path,
    start_sec: float,
    end_sec: float,
    aspect: str = "9:16",
    captions_path: str | Path | None = None,
    branding_srt_path: str | Path | None = None,
    caption_style: str = "bold",
    caption_position: str = "bottom",
    caption_font_size: int = 42,
    hook_path: str | Path | None = None,
    hook_position: str = "top",
    hook_duration: float = 2.5,
    logo_path: str | Path | None = None,
    logo_position: str = "top-right",
    logo_opacity: float = 0.85,
    music_path: str | Path | None = None,
    music_volume: float = 0.14,
    sfx_path: str | Path | None = None,
    sfx_volume: float = 0.35,
    speed: float = 1.0,
    effects: dict[str, Any] | None = None,
    smart_crop: bool = True,
) -> dict[str, Any]:
    """Render a real MP4 through FFmpeg. All user text is passed through text files."""
    source = Path(source_path)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    duration = max(0.5, float(end_sec) - float(start_sec))
    focus_x = detect_focus_x(source, start_sec, end_sec) if smart_crop else 0.5
    video_filter, _ = _aspect_filter(aspect, focus_x)
    filters = [video_filter]
    effects = effects or {}
    if speed and abs(float(speed) - 1.0) > 0.01:
        safe_speed = max(0.5, min(2.0, float(speed)))
        filters.append(f"setpts=PTS/{safe_speed:.3f}")
    if captions_path:
        if str(captions_path).lower().endswith(".ass"):
            filters.append(f"ass='{_filter_path(captions_path)}'")
        else:
            filters.append(f"subtitles='{_filter_path(captions_path)}':force_style='{_caption_style(caption_style, caption_position, caption_font_size)}'")
    if branding_srt_path and Path(branding_srt_path).exists():
        filters.append(f"subtitles='{_filter_path(branding_srt_path)}':force_style='{_caption_style('bold', 'middle', 46)}'")
    hook_srt_path: Path | None = None
    if hook_path and Path(hook_path).exists():
        hook_srt_path = output.with_name(output.stem + ".hook.srt")
        hook_text = Path(hook_path).read_text(encoding="utf-8").strip()
        hook_srt_path.write_text(
            f"1\n00:00:00,000 --> {_srt_timestamp(min(max(0.5, float(hook_duration)), duration))}\n{hook_text}\n\n",
            encoding="utf-8",
        )
        hook_style = _caption_style("bold", hook_position, max(28, min(54, int(caption_font_size))))
        filters.append(f"subtitles='{_filter_path(hook_srt_path)}':force_style='{hook_style}'")
    if effects.get("punch_zoom"):
        filters.append("scale=iw*1.06:ih*1.06,crop=iw/1.06:ih/1.06:(iw-ow)/2:(ih-oh)/2")
    if effects.get("fade"):
        fade_length = min(0.35, max(0.08, duration / 5))
        filters.append(f"fade=t=in:st=0:d={fade_length:.2f},fade=t=out:st={max(0.0, duration - fade_length):.2f}:d={fade_length:.2f}")
    if effects.get("shake"):
        filters.append("crop=iw-8:ih-8:4+2*sin(20*t):4+2*cos(18*t)")

    input_args: list[str] = ["-y", "-ss", f"{max(0.0, float(start_sec)):.3f}", "-t", f"{duration:.3f}", "-i", str(source)]
    logo_index: int | None = None
    music_index: int | None = None
    sfx_index: int | None = None
    if logo_path and Path(logo_path).exists():
        logo_index = 1
        input_args += ["-i", str(logo_path)]
    if music_path and Path(music_path).exists():
        music_index = 1 + int(logo_index is not None)
        input_args += ["-stream_loop", "-1", "-i", str(music_path)]
    if sfx_path and Path(sfx_path).exists():
        sfx_index = 1 + int(logo_index is not None) + int(music_index is not None)
        input_args += ["-stream_loop", "-1", "-i", str(sfx_path)]

    filter_complex: list[str] = []
    video_chain = "[0:v]" + ",".join(filters) + "[base]"
    filter_complex.append(video_chain)
    video_label = "[base]"
    if logo_index is not None:
        positions = {
            "top-left": "40:40", "top-right": "W-w-40:40", "bottom-left": "40:H-h-80", "bottom-right": "W-w-40:H-h-80"
        }
        xy = positions.get(logo_position, positions["top-right"])
        filter_complex.append(f"[{logo_index}:v]format=rgba,colorchannelmixer=aa={max(0.05, min(1.0, float(logo_opacity))):.2f}[logo]")
        filter_complex.append(f"[base][logo]overlay={xy}[vout]")
        video_label = "[vout]"
    else:
        video_label = "[base]"

    audio_inputs: list[tuple[int, float]] = []
    audio_inputs.append((0, 1.0))
    if music_index is not None:
        audio_inputs.append((music_index, max(0.0, min(1.0, float(music_volume)))))
    if sfx_index is not None:
        audio_inputs.append((sfx_index, max(0.0, min(1.0, float(sfx_volume)))))
    audio_label = None
    if len(audio_inputs) > 1:
        labels: list[str] = []
        for index, (input_index, volume) in enumerate(audio_inputs):
            label = f"a{index}"
            labels.append(f"[{input_index}:a]volume={volume:.3f}[{label}]")
        filter_complex.extend(labels)
        joined = "".join(f"[{f'a{i}'}]" for i in range(len(labels)))
        filter_complex.append(f"{joined}amix=inputs={len(labels)}:duration=first:dropout_transition=2[aout]")
        audio_label = "[aout]"

    args = input_args
    if filter_complex:
        args += ["-filter_complex", ";".join(filter_complex)]
    args += ["-map", video_label]
    if audio_label:
        args += ["-map", audio_label]
    else:
        args += ["-map", "0:a?"]
    args += [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", "-shortest", str(output),
    ]
    try:
        run_ffmpeg(args, timeout=900)
    except FFmpegError:
        # A missing/invalid optional audio asset should not prevent a video-only render.
        if music_index is not None or sfx_index is not None:
            fallback = ["-y", "-ss", f"{max(0.0, float(start_sec)):.3f}", "-t", f"{duration:.3f}", "-i", str(source)]
            fallback_filter = list(filters)
            fallback += ["-vf", ",".join(fallback_filter), "-map", "0:v", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", "-shortest", str(output)]
            run_ffmpeg(fallback, timeout=900)
        else:
            raise
    if not output.exists() or output.stat().st_size < 1024:
        raise FFmpegError("FFmpeg returned successfully but the exported video is empty or invalid.")
    return {"path": str(output), "size_bytes": output.stat().st_size, "duration": duration, "aspect": aspect, "focus_x": round(focus_x, 3), "smart_crop": smart_crop}


def make_thumbnail(video_path: str | Path, output_path: str | Path, time_sec: float = 0.5) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg([
        "-y", "-ss", str(max(0.0, time_sec)), "-i", str(video_path), "-frames:v", "1", "-vf", "scale=480:-2", str(output)
    ], timeout=120)
    return output
