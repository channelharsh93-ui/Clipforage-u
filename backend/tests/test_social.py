import os

from app.services.social_platforms import list_provider_metadata


def test_social_providers_do_not_fake_connections(monkeypatch):
    for key in ["YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "META_APP_ID", "META_APP_SECRET", "TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET"]:
        monkeypatch.delenv(key, raising=False)
    providers = list_provider_metadata()
    assert {item["id"] for item in providers} == {"youtube", "facebook", "instagram", "tiktok"}
    assert all(item["configured"] is False for item in providers)
