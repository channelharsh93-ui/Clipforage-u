from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any


def detect_scenes(video_path: str | Path, duration: float, fps: float = 30.0) -> tuple[list[dict[str, Any]], list[float]]:
    """Lightweight scene detection using OpenCV histogram differences."""
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return _fallback_scenes(duration), []
        actual_fps = float(cap.get(cv2.CAP_PROP_FPS) or fps or 30.0)
        sample_every = max(1, int(actual_fps * 0.5))
        frame_number = 0
        last_cut = 0.0
        cuts: list[float] = []
        previous = None
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if frame_number % sample_every != 0:
                frame_number += 1
                continue
            current_time = frame_number / actual_fps
            small = cv2.resize(frame, (96, 54))
            hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
            hist = cv2.calcHist([hsv], [0, 1], None, [16, 16], [0, 180, 0, 256])
            cv2.normalize(hist, hist)
            if previous is not None:
                difference = float(cv2.compareHist(previous, hist, cv2.HISTCMP_BHATTACHARYYA))
                if difference > 0.42 and current_time - last_cut > 1.4:
                    cuts.append(round(current_time, 3))
                    last_cut = current_time
            previous = hist
            frame_number += 1
        cap.release()
        scenes = []
        boundaries = [0.0] + cuts + [max(0.1, duration)]
        for start, end in zip(boundaries, boundaries[1:]):
            if end - start >= 0.35:
                scenes.append({"start": round(start, 3), "end": round(end, 3), "duration": round(end - start, 3)})
        if not scenes:
            scenes = _fallback_scenes(duration)
        return scenes, cuts
    except Exception:
        return _fallback_scenes(duration), []


def _fallback_scenes(duration: float) -> list[dict[str, Any]]:
    scenes = []
    cursor = 0.0
    while cursor < max(duration, 0.1):
        end = min(max(duration, 0.1), cursor + 15.0)
        scenes.append({"start": round(cursor, 3), "end": round(end, 3), "duration": round(end - cursor, 3)})
        cursor = end
    return scenes


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _overlap(a: dict[str, Any], b: dict[str, Any]) -> float:
    intersection = max(0.0, min(a["end"], b["end"]) - max(a["start"], b["start"]))
    shorter = max(0.001, min(a["end"] - a["start"], b["end"] - b["start"]))
    return intersection / shorter


def _merge_window(start: float, end: float, duration: float, min_len: float = 15.0, max_len: float = 60.0) -> tuple[float, float]:
    if end - start < min_len:
        padding = (min_len - (end - start)) / 2
        start -= padding
        end += padding
    if end - start > max_len:
        center = (start + end) / 2
        start = center - max_len / 2
        end = center + max_len / 2
    return round(_clamp(start, 0.0, max(0.1, duration)), 3), round(_clamp(end, 0.1, max(0.1, duration)), 3)


def _transcript_text(segments: list[dict[str, Any]], start: float, end: float) -> str:
    parts = []
    for segment in segments:
        if float(segment.get("end", 0)) >= start and float(segment.get("start", 0)) <= end:
            parts.append(str(segment.get("text", "")).strip())
    return " ".join(part for part in parts if part).strip()


def _audio_stats(audio: list[dict[str, float]], start: float, end: float) -> dict[str, float]:
    relevant = [item for item in audio if item["end"] >= start and item["start"] <= end]
    if not relevant:
        return {"mean": 0.0, "peak": 0.0, "relative": 0.0}
    return {
        "mean": sum(item.get("rms", 0.0) for item in relevant) / len(relevant),
        "peak": max(item.get("peak", 0.0) for item in relevant),
        "relative": max(item.get("relative", 0.0) for item in relevant),
    }


CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "FUNNY": ("laugh", "funny", "hilarious", "joke", "joking", "comedy", "ridiculous", "laughing", "roast"),
    "DRAMATIC": ("never", "everything changed", "dramatic", "crisis", "heartbreak", "confession", "truth"),
    "ACTION": ("fight", "run", "jump", "win", "race", "attack", "action", "game", "beat"),
    "EMOTIONAL": ("love", "miss", "cry", "tears", "family", "proud", "feel", "emotional", "grateful"),
    "SHOCKING": ("shocking", "unbelievable", "no way", "what", "seriously", "cannot believe", "secret", "revealed"),
    "MOTIVATIONAL": ("believe", "discipline", "success", "dream", "goal", "keep going", "motivation", "work hard"),
    "EDUCATIONAL": ("how to", "because", "why", "learn", "tip", "explained", "lesson", "step", "mistake"),
    "STORY": ("story", "then", "after that", "when i", "once", "years ago", "happened"),
    "REACTION": ("reaction", "wait", "what did", "you did", "really", "wow", "oh my"),
    "SUSPENSE": ("next", "wait for", "secret", "discover", "turns out", "suspense", "before"),
    "DEBATE": ("agree", "disagree", "opinion", "debate", "wrong", "right", "should", "versus"),
}


def classify(text: str) -> str:
    normalized = text.lower()
    scores = {
        category: sum(1 for keyword in keywords if keyword in normalized)
        for category, keywords in CATEGORY_KEYWORDS.items()
    }
    best = max(scores, key=scores.get) if scores else "OTHER"
    return best if scores.get(best, 0) > 0 else "INTERESTING"


def make_hook(text: str) -> str:
    clean = " ".join(text.split())
    if not clean:
        return "A moment worth watching"
    clean = re.sub(r"^[\-–—:]+", "", clean).strip()
    words = clean.split()
    preview = " ".join(words[:10])
    if len(words) > 10:
        preview += "…"
    return f"Listen to this: {preview}"


def make_title(category: str, text: str, rank: int) -> str:
    clean = " ".join(text.split())
    if clean:
        words = clean.split()
        title = " ".join(words[:8])
        if len(words) > 8:
            title += "…"
        return title[:72]
    return f"{category.title()} moment #{rank}"


def make_title_suggestions(category: str, text: str, rank: int) -> list[str]:
    clean = " ".join(text.split())
    first = make_title(category, clean, rank)
    suggestions = [first]
    if clean:
        suggestions.extend([
            f"{category.title()} moment: {first[:45]}",
            f"What happened next in this {category.lower()} moment",
            f"A closer look at: {first[:48]}",
        ])
    else:
        suggestions.extend([
            f"A {category.lower()} moment worth watching",
            "Watch this moment from the full video",
            "A standout moment from the source",
        ])
    unique: list[str] = []
    for suggestion in suggestions:
        clean_suggestion = suggestion.strip().rstrip(".")[:90]
        if clean_suggestion and clean_suggestion.lower() not in {item.lower() for item in unique}:
            unique.append(clean_suggestion)
    return unique[:4]


def make_hashtags(category: str, text: str) -> list[str]:
    tags = ["shorts", "reels", category.lower()]
    for word in re.findall(r"[a-zA-Z]{4,}", text.lower()):
        if word not in {"this", "that", "with", "from", "your", "what", "when", "have", "actually"} and word not in tags:
            tags.append(word)
        if len(tags) >= 5:
            break
    return [f"#{tag}" for tag in tags]


def generate_candidates(
    duration: float,
    transcript: list[dict[str, Any]],
    scenes: list[dict[str, Any]],
    audio: list[dict[str, float]],
    cuts: list[float],
    max_candidates: int = 40,
) -> list[dict[str, Any]]:
    raw: list[dict[str, Any]] = []

    # Speech-led candidates include setup and payoff, rather than only one sentence.
    for segment in transcript:
        start, end = _merge_window(float(segment.get("start", 0)) - 4.0, float(segment.get("end", 0)) + 5.0, duration)
        raw.append({"start": start, "end": end, "source": "speech"})

    # Group nearby speech segments into a complete mini-story.
    if transcript:
        group_start = float(transcript[0].get("start", 0))
        group_end = float(transcript[0].get("end", 0))
        for segment in transcript[1:]:
            seg_start = float(segment.get("start", 0))
            seg_end = float(segment.get("end", 0))
            if seg_start - group_end <= 4.5 and seg_end - group_start <= 52:
                group_end = seg_end
            else:
                start, end = _merge_window(group_start - 4, group_end + 5, duration)
                raw.append({"start": start, "end": end, "source": "story"})
                group_start, group_end = seg_start, seg_end
        start, end = _merge_window(group_start - 4, group_end + 5, duration)
        raw.append({"start": start, "end": end, "source": "story"})

    # Scene candidates provide useful output even if there is little/no speech.
    for scene in scenes:
        if scene["duration"] >= 1.0:
            start, end = _merge_window(scene["start"] - 2, scene["end"] + 3, duration)
            raw.append({"start": start, "end": end, "source": "scene"})

    # Audio peaks are a signal, never the complete decision.
    for window in sorted(audio, key=lambda item: (item.get("relative", 0), item.get("peak", 0)), reverse=True)[:12]:
        if window.get("relative", 0) < 1.12:
            continue
        start, end = _merge_window(window["start"] - 9, window["end"] + 9, duration)
        raw.append({"start": start, "end": end, "source": "audio_peak"})

    if not raw:
        cursor = 0.0
        while cursor < duration:
            start, end = _merge_window(cursor, cursor + 30, duration)
            raw.append({"start": start, "end": end, "source": "fallback"})
            cursor += 24

    # Merge heavily overlapping candidates and retain provenance.
    deduped: list[dict[str, Any]] = []
    for candidate in sorted(raw, key=lambda item: (item["start"], item["end"])):
        existing = next((item for item in deduped if _overlap(item, candidate) > 0.72), None)
        if existing:
            existing["source"] = f"{existing['source']},{candidate['source']}"
        else:
            deduped.append(candidate)
    return deduped[:max_candidates]


def score_candidates(
    candidates: list[dict[str, Any]],
    transcript: list[dict[str, Any]],
    scenes: list[dict[str, Any]],
    audio: list[dict[str, float]],
    cuts: list[float],
) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    for candidate in candidates:
        start, end = candidate["start"], candidate["end"]
        duration = end - start
        text = _transcript_text(transcript, start, end)
        normalized = text.lower()
        audio_stat = _audio_stats(audio, start, end)
        words = len(text.split())
        speech_density = _clamp(words / max(1.0, duration * 2.2), 0.0, 1.0)
        emotional_words = sum(1 for token in re.findall(r"[a-z']+", normalized) if token in {
            "wow", "wait", "never", "love", "hate", "amazing", "crazy", "unbelievable", "why", "how", "actually", "truth", "secret"
        })
        emotion = _clamp(emotional_words / 4, 0.0, 1.0)
        punctuation = _clamp((text.count("!") * 0.18) + (text.count("?") * 0.12), 0.0, 1.0)
        scene_signal = _clamp(sum(1 for cut in cuts if start <= cut <= end) / 3, 0.0, 1.0)
        audio_signal = _clamp((audio_stat["relative"] - 0.8) / 1.5, 0.0, 1.0)
        completeness = 1.0 if text and (text.endswith((".", "!", "?")) or duration >= 22) else 0.58
        length_score = 1.0 if 15 <= duration <= 45 else 0.75 if 10 <= duration <= 60 else 0.45
        category = classify(text)
        category_bonus = 0.1 if category not in {"INTERESTING", "OTHER"} else 0.0
        score = 100 * (
            0.22 * emotion
            + 0.18 * speech_density
            + 0.14 * audio_signal
            + 0.10 * scene_signal
            + 0.12 * punctuation
            + 0.14 * completeness
            + 0.10 * length_score
        )
        score = _clamp(score + category_bonus * 100, 1.0, 99.0)
        if text:
            reason_parts = []
            if emotion > 0.25:
                reason_parts.append("emotionally charged wording")
            if audio_signal > 0.35:
                reason_parts.append("an audio intensity change")
            if scene_signal > 0.2:
                reason_parts.append("a visual scene change")
            if punctuation > 0.15:
                reason_parts.append("a question or emphatic delivery")
            reason = "Strong " + ", ".join(reason_parts[:2]) if reason_parts else "Complete speech segment with enough context for a short story"
        else:
            reason = "Visual and audio activity candidate; review the preview before publishing"
        scored.append({
            **candidate,
            "duration": round(duration, 3),
            "transcript": [{
                "start": max(start, float(item.get("start", 0))),
                "end": min(end, float(item.get("end", 0))),
                "text": item.get("text", ""),
                "words": item.get("words", []),
            } for item in transcript if float(item.get("end", 0)) >= start and float(item.get("start", 0)) <= end],
            "text": text,
            "category": category,
            "score": round(score, 1),
            "reason": reason,
            "hook": make_hook(text),
            "title": make_title(category, text, len(scored) + 1),
            "title_suggestions": make_title_suggestions(category, text, len(scored) + 1),
            "description": text[:240] if text else "A visually active moment selected from the source video.",
            "hashtags": make_hashtags(category, text),
            "signals": {
                "emotion": round(emotion, 3), "speech_density": round(speech_density, 3),
                "audio_intensity": round(audio_signal, 3), "scene_change": round(scene_signal, 3),
                "completeness": round(completeness, 3), "length_fit": round(length_score, 3),
            },
        })

    # Non-maximum suppression: avoid five versions of the same moment.
    selected: list[dict[str, Any]] = []
    for item in sorted(scored, key=lambda entry: entry["score"], reverse=True):
        if any(_overlap(item, kept) > 0.68 for kept in selected):
            continue
        selected.append(item)
    for rank, item in enumerate(selected, 1):
        item["rank"] = rank
        item["title"] = make_title(item["category"], item.get("text", ""), rank)
    return selected
