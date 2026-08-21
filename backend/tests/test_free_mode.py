from app.ads import AdManager
from app.plans import PLANS
from app.services.content_generator import LocalAIProvider


def test_free_plan_is_local_and_daily_capped():
    free = PLANS["free"]
    assert free["price_inr_monthly"] == 0
    assert free["limits"]["daily_clips"] == 10
    assert free["entitlements"]["platform_publish"] is False
    assert free["entitlements"]["full_content_pack"] is False


def test_pro_does_not_show_demo_ads(monkeypatch):
    monkeypatch.setattr("app.ads.current_plan_id", lambda: "pro")
    assert AdManager().can_show_ad("test-session", "projects") is False


def test_local_provider_exposes_core_ai_operations():
    provider = LocalAIProvider()
    clip = {"category": "FUNNY", "title": "Demo", "score": 90, "transcript": [{"text": "This is a funny moment."}]}
    pack = provider.generate_content_pack(clip)
    assert provider.provider_id == "local-deterministic"
    assert provider.analyze_video([], [], [])["network_calls"] == 0
    assert len(provider.generate_hook(clip)) >= 1
    assert len(provider.generate_title(clip)) >= 1
    assert pack["seo"]["score"] >= 0
