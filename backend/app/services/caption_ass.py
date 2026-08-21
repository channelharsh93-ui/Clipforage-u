from __future__ import annotations

from pathlib import Path
from typing import Any


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours}:{minutes:02d}:{secs:05.2f}"


def _escape_text(value: str) -> str:
    return str(value).replace("{", "(").replace("}", ")").replace("\\", "")


def _style(style: str, position: str, font_size: int) -> str:
    colors = {
        "clean": ("&H00FFFFFF", "&H0000FFFF"),
        "bold": ("&H00FFFFFF", "&H0000FFFF"),
        "creator": ("&H0000FFFF", "&H00FFFFFF"),
        "podcast": ("&H00FFFFFF", "&H0000FFFF"),
        "minimal": ("&H00FFFFFF", "&H0000FFFF"),
        "high-energy": ("&H0000FFFF", "&H00FFFFFF"),
    }
    primary, secondary = colors.get(style, colors["bold"])
    alignment = 8 if position == "top" else 5 if position == "middle" else 2
    size = max(18, min(72, int(font_size)))
    return f"Style: Default,Arial,{size},{primary},{secondary},&H00101010,&H80101010,1,0,0,0,100,100,0,0,1,2,1,2,{alignment},60,60,100"


def write_caption_ass(transcript: list[dict[str, Any]], clip_start: float, clip_end: float, output_path: str | Path, style: str = "bold", position: str = "bottom", font_size: int = 42, max_words: int = 7) -> Path | None:
    events: list[tuple[float, float, str]] = []
    for segment in transcript:
        start = max(clip_start, float(segment.get("start", 0))) - clip_start
        end = min(clip_end, float(segment.get("end", 0))) - clip_start
        words = [word for word in (segment.get("words") or []) if word.get("word")]
        if end <= start:
            continue
        if not words:
            events.append((start, end, _escape_text(segment.get("text", ""))))
            continue
        for offset in range(0, len(words), max_words):
            group = words[offset:offset + max_words]
            group_start = max(start, float(group[0].get("start", start)) - clip_start)
            group_end = min(end, float(group[-1].get("end", end)) - clip_start)
            if group_end <= group_start:
                continue
            parts = ["{\\fad(100,100)}"]
            for word in group:
                word_start = float(word.get("start", start))
                word_end = float(word.get("end", word_start + 0.2))
                duration_cs = max(1, round((word_end - word_start) * 100))
                parts.append(f"{{\\kf{duration_cs}}}{_escape_text(str(word.get('word', '')).strip())} ")
            events.append((group_start, group_end, "".join(parts).strip()))
    if not events:
        return None
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "[Script Info]", "ScriptType: v4.00+", "PlayResX: 1080", "PlayResY: 1920", "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]", "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding", _style(style, position, font_size), "",
        "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for start, end, text in events:
        lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,{text}")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output
