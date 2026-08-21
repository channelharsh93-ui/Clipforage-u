from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

from .config import ALLOW_CLOUD_AI, LOCAL_AI, LOCAL_MODEL
from .privacy import privacy_mode


def system_status() -> dict[str, Any]:
    cpu = None
    memory = None
    try:
        import psutil  # type: ignore
        cpu = psutil.cpu_percent(interval=0.05)
        memory = psutil.virtual_memory().percent
    except Exception:
        pass
    gpu = {"available": False, "name": None, "memory_used_mb": None, "memory_total_mb": None}
    nvidia = shutil.which("nvidia-smi")
    if nvidia:
        try:
            result = subprocess.run([nvidia, "--query-gpu=name,memory.used,memory.total", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=2)
            line = (result.stdout or "").strip().splitlines()[0]
            name, used, total = [part.strip() for part in line.split(",")]
            gpu = {"available": True, "name": name, "memory_used_mb": float(used), "memory_total_mb": float(total)}
        except Exception:
            pass
    return {
        "running_locally": bool(LOCAL_AI and not ALLOW_CLOUD_AI),
        "privacy_mode": privacy_mode(),
        "ai_provider": "local" if LOCAL_AI else "disabled",
        "local_model": LOCAL_MODEL,
        "cloud_ai_allowed": ALLOW_CLOUD_AI,
        "cpu_percent": cpu,
        "memory_percent": memory,
        "gpu": gpu,
        "message": "Running locally — no external AI provider is active." if LOCAL_AI and not ALLOW_CLOUD_AI else "Review AI provider configuration.",
    }
