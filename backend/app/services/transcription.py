from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from ..config import WHISPER_MODEL

_model = None
_model_lock = threading.Lock()


def _get_model(model_name: str = WHISPER_MODEL):
    global _model
    with _model_lock:
        if _model is not None:
            return _model
        from faster_whisper import WhisperModel  # type: ignore

        _model = WhisperModel(model_name, device="cpu", compute_type="int8")
        return _model


def transcribe(audio_path: str | Path, model_name: str = WHISPER_MODEL) -> dict[str, Any]:
    """Local transcription provider. No network API is used; the model downloads once from Hugging Face if absent."""
    try:
        model = _get_model(model_name)
        segments, info = model.transcribe(
            str(audio_path),
            beam_size=1,
            vad_filter=True,
            word_timestamps=True,
            condition_on_previous_text=False,
        )
        output: list[dict[str, Any]] = []
        for segment in segments:
            words = []
            for word in getattr(segment, "words", None) or []:
                words.append({
                    "word": str(getattr(word, "word", "")).strip(),
                    "start": float(getattr(word, "start", segment.start) or segment.start),
                    "end": float(getattr(word, "end", segment.end) or segment.end),
                })
            text = str(getattr(segment, "text", "")).strip()
            if text:
                output.append({
                    "start": round(float(segment.start), 3),
                    "end": round(float(segment.end), 3),
                    "text": text,
                    "words": words,
                    "confidence": round(float(getattr(segment, "avg_logprob", 0.0)), 4),
                })
        return {
            "provider": "faster-whisper",
            "model": model_name,
            "language": getattr(info, "language", None),
            "segments": output,
            "word_timestamps": True,
            "notice": "Transcription was performed locally with an open-source Whisper model.",
        }
    except ImportError:
        return {
            "provider": "unavailable",
            "model": model_name,
            "language": None,
            "segments": [],
            "word_timestamps": False,
            "notice": "Local transcription is unavailable because faster-whisper is not installed. Install backend requirements to enable captions.",
        }
    except Exception as exc:
        return {
            "provider": "failed",
            "model": model_name,
            "language": None,
            "segments": [],
            "word_timestamps": False,
            "notice": f"Local transcription failed: {str(exc)[-500:]}",
        }
