from __future__ import annotations

import os
import secrets
import time
from dataclasses import dataclass
from threading import Lock
from typing import Any

from .plans import current_plan_id


@dataclass(frozen=True)
class Ad:
    id: str
    label: str
    title: str
    body: str
    accent: str
    click_url: str | None = None


class AdProvider:
    provider_id = "base"

    def load_ad(self, page: str, device: str) -> Ad | None:
        raise NotImplementedError

    def show_ad(self, ad: Ad) -> dict[str, Any]:
        return ad.__dict__.copy()

    def record_impression(self, ad: Ad, page: str, device: str) -> None:
        return None

    def record_click(self, ad: Ad, page: str, device: str) -> None:
        return None


class DemoAdProvider(AdProvider):
    provider_id = "demo"
    _ads = (
        Ad("demo-local-creator", "Sponsored · Demo placement", "Make your next clip easier to publish", "A quiet example of a clearly labeled ClipForge sponsorship. No redirect, autoplay, or required click.", "mint"),
        Ad("demo-open-source", "Sponsored · Open-source toolkit", "Local tools for independent creators", "Keep your workflow local-first with transparent tools and no hidden provider charges.", "purple"),
    )

    def load_ad(self, page: str, device: str) -> Ad | None:
        # The demo provider is intentionally static and self-contained. A real provider
        # can be plugged in later without changing placements or frequency rules.
        return self._ads[int(time.time() / 120) % len(self._ads)]


@dataclass
class SessionState:
    shown_count: int = 0
    last_shown_at: float = 0.0
    shown_ids: tuple[str, ...] = ()


class AdManager:
    def __init__(self, provider: AdProvider | None = None) -> None:
        self.provider = provider or DemoAdProvider()
        self.lock = Lock()
        self.sessions: dict[str, SessionState] = {}
        self.metrics = {"impressions": 0, "clicks": 0, "by_page": {}, "by_device": {}}

    @property
    def enabled(self) -> bool:
        return os.getenv("ADS_ENABLED", "true").lower() not in {"0", "false", "off", "no"}

    @property
    def max_ads_per_session(self) -> int:
        return max(0, int(os.getenv("MAX_ADS_PER_SESSION", "5")))

    @property
    def min_interval_seconds(self) -> int:
        return max(0, int(os.getenv("MIN_AD_INTERVAL_SECONDS", "120")))

    @property
    def user_plan(self) -> str:
        return current_plan_id()

    def can_show_ad(self, session_id: str, page: str) -> bool:
        if not self.enabled or self.user_plan in {"premium", "pro"}:
            return False
        if page in {"editor", "processing", "download", "publishing"}:
            return False
        with self.lock:
            state = self.sessions.get(session_id, SessionState())
            if state.shown_count >= self.max_ads_per_session:
                return False
            if time.time() - state.last_shown_at < self.min_interval_seconds:
                return False
            return True

    def get_ad(self, session_id: str, page: str, device: str) -> dict[str, Any] | None:
        if not self.can_show_ad(session_id, page):
            return None
        ad = self.provider.load_ad(page, device)
        if not ad:
            return None
        now = time.time()
        with self.lock:
            old = self.sessions.get(session_id, SessionState())
            shown_ids = list(old.shown_ids)
            if ad.id in shown_ids and len(shown_ids) < 2:
                return None
            shown_ids.append(ad.id)
            self.sessions[session_id] = SessionState(old.shown_count + 1, now, tuple(shown_ids[-5:]))
        payload = self.provider.show_ad(ad)
        payload.update({"provider": self.provider.provider_id, "page": page, "device": device, "frequency": {"shown": old.shown_count + 1, "max": self.max_ads_per_session, "next_after_seconds": self.min_interval_seconds}})
        return payload

    def record_impression(self, ad_id: str, page: str, device: str) -> None:
        with self.lock:
            self.metrics["impressions"] += 1
            self.metrics["by_page"][page] = self.metrics["by_page"].get(page, 0) + 1
            self.metrics["by_device"][device] = self.metrics["by_device"].get(device, 0) + 1

    def record_click(self, ad_id: str, page: str, device: str) -> None:
        with self.lock:
            self.metrics["clicks"] += 1

    def config(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "user_plan": self.user_plan, "max_ads_per_session": self.max_ads_per_session, "min_ad_interval_seconds": self.min_interval_seconds, "provider": self.provider.provider_id}

    def metrics_snapshot(self) -> dict[str, Any]:
        with self.lock:
            snapshot = dict(self.metrics)
            snapshot["ctr"] = round(snapshot["clicks"] / snapshot["impressions"] * 100, 2) if snapshot["impressions"] else 0
            return snapshot


ad_manager = AdManager()
