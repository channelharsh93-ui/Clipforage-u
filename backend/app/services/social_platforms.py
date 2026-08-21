from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx


GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v20.0")


@dataclass(frozen=True)
class PlatformMeta:
    id: str
    name: str
    short_name: str
    color: str
    configured_env: tuple[str, ...]
    capabilities: dict[str, bool]
    note: str


class SocialPlatformProvider(ABC):
    meta: PlatformMeta

    def is_configured(self) -> bool:
        return all(bool(os.getenv(key, "").strip()) for key in self.meta.configured_env)

    def authenticate(self, redirect_uri: str, state: str, purpose: str = "import") -> dict[str, Any]:
        return {"authorization_url": self.get_authorization_url(redirect_uri, state, purpose), "purpose": purpose}

    def disconnect(self, connection: dict[str, Any]) -> dict[str, Any]:
        # OAuth revocation is platform-specific. Local disconnect always deletes the encrypted token;
        # providers can override this when an official revocation endpoint is available.
        return {"ok": True, "local_token_deleted": True}

    @abstractmethod
    def get_authorization_url(self, redirect_uri: str, state: str, purpose: str = "import") -> str:
        raise NotImplementedError

    @abstractmethod
    def exchange_code(self, code: str, redirect_uri: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_account(self, access_token: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_user_videos(self, connection: dict[str, Any]) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_video_metadata(self, connection: dict[str, Any], video_id: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_video_media(self, connection: dict[str, Any], video: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def publish_video(self, connection: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def _get(self, url: str, token: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = httpx.get(url, headers={"Authorization": f"Bearer {token}"}, params=params or {}, timeout=45)
        if response.status_code >= 400:
            raise RuntimeError(_friendly_http_error(response))
        return response.json()

    def _post(self, url: str, token: str, payload: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = httpx.post(url, headers={"Authorization": f"Bearer {token}"}, json=payload or {}, params=params or {}, timeout=60)
        if response.status_code >= 400:
            raise RuntimeError(_friendly_http_error(response))
        return response.json()


def _friendly_http_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
        error = payload.get("error", payload)
        if isinstance(error, dict):
            message = error.get("message") or error.get("error_description") or error.get("detail")
            if message:
                return str(message)
        return str(payload)[:500]
    except Exception:
        return f"Platform returned HTTP {response.status_code}."


def _iso_from_epoch(value: Any) -> str | None:
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    except Exception:
        return None


def _youtube_duration(value: str | None) -> float | None:
    if not value:
        return None
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", value)
    if not match:
        return None
    return (int(match.group(1) or 0) * 3600) + (int(match.group(2) or 0) * 60) + float(match.group(3) or 0)


class YouTubeProvider(SocialPlatformProvider):
    meta = PlatformMeta(
        id="youtube", name="YouTube", short_name="YT", color="#ff5b63",
        configured_env=("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET"),
        capabilities={"import_metadata": True, "import_media": False, "publish": True, "schedule": False, "thumbnail": True},
        note="YouTube Data API can list your videos and publish, but does not provide an authorized original-media download endpoint for this workflow.",
    )

    def get_authorization_url(self, redirect_uri: str, state: str, purpose: str = "import") -> str:
        scopes = ["https://www.googleapis.com/auth/youtube.readonly"]
        if purpose == "publish":
            scopes = ["https://www.googleapis.com/auth/youtube.upload"]
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
            "client_id": os.getenv("YOUTUBE_CLIENT_ID"), "redirect_uri": redirect_uri,
            "response_type": "code", "access_type": "offline", "prompt": "consent",
            "scope": " ".join(scopes), "state": state,
        })

    def exchange_code(self, code: str, redirect_uri: str) -> dict[str, Any]:
        response = httpx.post("https://oauth2.googleapis.com/token", data={
            "code": code, "client_id": os.getenv("YOUTUBE_CLIENT_ID"), "client_secret": os.getenv("YOUTUBE_CLIENT_SECRET"),
            "redirect_uri": redirect_uri, "grant_type": "authorization_code",
        }, timeout=45)
        if response.status_code >= 400:
            raise RuntimeError(_friendly_http_error(response))
        return response.json()

    def get_account(self, access_token: str) -> dict[str, Any]:
        data = self._get("https://www.googleapis.com/youtube/v3/channels", access_token, {"part": "snippet,contentDetails", "mine": "true"})
        item = (data.get("items") or [{}])[0]
        return {
            "account_id": item.get("id", "youtube-user"),
            "account_name": (item.get("snippet") or {}).get("title", "YouTube account"),
            "metadata": {"uploads_playlist_id": (item.get("contentDetails") or {}).get("relatedPlaylists", {}).get("uploads")},
        }

    def get_user_videos(self, connection: dict[str, Any]) -> list[dict[str, Any]]:
        token = connection["access_token"]
        uploads = (connection.get("metadata") or {}).get("uploads_playlist_id")
        if not uploads:
            account = self.get_account(token)
            uploads = (account.get("metadata") or {}).get("uploads_playlist_id")
        if not uploads:
            return []
        playlist = self._get("https://www.googleapis.com/youtube/v3/playlistItems", token, {"part": "contentDetails", "playlistId": uploads, "maxResults": 50})
        ids = [item.get("contentDetails", {}).get("videoId") for item in playlist.get("items", [])]
        ids = [item for item in ids if item]
        if not ids:
            return []
        videos = self._get("https://www.googleapis.com/youtube/v3/videos", token, {"part": "snippet,contentDetails,statistics", "id": ",".join(ids)})
        result = []
        for item in videos.get("items", []):
            snippet = item.get("snippet") or {}
            details = item.get("contentDetails") or {}
            stats = item.get("statistics") or {}
            result.append({
                "id": item.get("id"), "title": snippet.get("title", "Untitled video"),
                "thumbnail_url": (snippet.get("thumbnails") or {}).get("medium", {}).get("url"),
                "duration": _youtube_duration(details.get("duration")), "created_at": snippet.get("publishedAt"),
                "platform": "YouTube", "views": int(stats.get("viewCount", 0) or 0),
                "media_import_available": False, "permalink": f"https://www.youtube.com/watch?v={item.get('id')}",
            })
        return result

    def get_video_metadata(self, connection: dict[str, Any], video_id: str) -> dict[str, Any]:
        data = self._get("https://www.googleapis.com/youtube/v3/videos", connection["access_token"], {"part": "snippet,contentDetails,statistics", "id": video_id})
        items = data.get("items") or []
        if not items:
            raise RuntimeError("YouTube video was not found in the connected account.")
        return {
            "id": video_id, "title": (items[0].get("snippet") or {}).get("title", "Untitled video"),
            "media_import_available": False, "platform": "YouTube",
        }

    def get_video_media(self, connection: dict[str, Any], video: dict[str, Any]) -> dict[str, Any]:
        return {"supported": False, "reason": "YouTube's current Data API does not provide an authorized original-video download method for this workflow. Upload the video file instead."}

    def publish_video(self, connection: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        if "https://www.googleapis.com/auth/youtube.upload" not in connection.get("scopes", []):
            return {"supported": False, "reason": "Reconnect YouTube with publishing permission before publishing. No password or token paste is required."}
        path = Path(payload.get("local_path", ""))
        if not path.exists():
            return {"supported": False, "reason": "The rendered clip is no longer available locally."}
        token = connection["access_token"]
        metadata = {
            "snippet": {"title": payload.get("title") or "ClipForge clip", "description": payload.get("caption", ""), "tags": payload.get("hashtags", [])},
            "status": {"privacyStatus": payload.get("visibility", "private")},
        }
        init = httpx.post(
            "https://www.googleapis.com/upload/youtube/v3/videos",
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8", "X-Upload-Content-Length": str(path.stat().st_size), "X-Upload-Content-Type": "video/mp4"},
            json=metadata, timeout=60,
        )
        if init.status_code >= 400:
            return {"supported": False, "reason": _friendly_http_error(init)}
        location = init.headers.get("Location")
        if not location:
            return {"supported": False, "reason": "YouTube did not return an upload session."}
        upload = httpx.put(location, headers={"Authorization": f"Bearer {token}", "Content-Type": "video/mp4", "Content-Length": str(path.stat().st_size)}, content=path.read_bytes(), timeout=600)
        if upload.status_code >= 400:
            return {"supported": False, "reason": _friendly_http_error(upload)}
        body = upload.json()
        remote_id = body.get("id")
        warning = None
        thumbnail_path = Path(payload.get("thumbnail_path", ""))
        if remote_id and thumbnail_path.exists():
            thumbnail_response = httpx.post(
                "https://www.googleapis.com/upload/youtube/v3/thumbnails/set",
                params={"videoId": remote_id},
                headers={"Authorization": f"Bearer {token}", "Content-Type": "image/jpeg"},
                content=thumbnail_path.read_bytes(), timeout=120,
            )
            if thumbnail_response.status_code >= 400:
                warning = f"Video published, but YouTube rejected the thumbnail: {_friendly_http_error(thumbnail_response)}"
        return {"supported": True, "published": True, "remote_id": remote_id, "permalink": f"https://www.youtube.com/watch?v={remote_id}", "warning": warning}


class MetaProvider(SocialPlatformProvider):
    def __init__(self, platform_id: str):
        self.meta = PlatformMeta(
            id=platform_id, name="Instagram" if platform_id == "instagram" else "Facebook", short_name="IG" if platform_id == "instagram" else "f", color="#e6688a" if platform_id == "instagram" else "#6d8dff",
            configured_env=("META_APP_ID", "META_APP_SECRET"),
            capabilities={"import_metadata": True, "import_media": True, "publish": platform_id == "facebook", "schedule": False},
            note="Meta permissions and account type determine which media and publishing actions are available.",
        )

    def get_authorization_url(self, redirect_uri: str, state: str, purpose: str = "import") -> str:
        scopes = ["public_profile"]
        if self.meta.id == "facebook":
            scopes += ["pages_show_list", "pages_read_engagement"]
            if purpose == "publish": scopes += ["pages_manage_posts"]
        else:
            scopes += ["instagram_basic"]
            if purpose == "publish": scopes += ["instagram_content_publish"]
        return f"https://www.facebook.com/{GRAPH_VERSION}/dialog/oauth?" + urlencode({
            "client_id": os.getenv("META_APP_ID"), "redirect_uri": redirect_uri, "state": state,
            "response_type": "code", "scope": ",".join(scopes),
        })

    def exchange_code(self, code: str, redirect_uri: str) -> dict[str, Any]:
        response = httpx.get(f"https://graph.facebook.com/{GRAPH_VERSION}/oauth/access_token", params={
            "client_id": os.getenv("META_APP_ID"), "client_secret": os.getenv("META_APP_SECRET"), "redirect_uri": redirect_uri, "code": code,
        }, timeout=45)
        if response.status_code >= 400:
            raise RuntimeError(_friendly_http_error(response))
        return response.json()

    def get_account(self, access_token: str) -> dict[str, Any]:
        user = self._get(f"https://graph.facebook.com/{GRAPH_VERSION}/me", access_token, {"fields": "id,name"})
        pages_data = self._get(f"https://graph.facebook.com/{GRAPH_VERSION}/me/accounts", access_token, {"fields": "id,name,access_token,instagram_business_account"})
        pages = []
        for page in pages_data.get("data", []):
            pages.append({"id": page.get("id"), "name": page.get("name"), "access_token": page.get("access_token"), "instagram_business_account": page.get("instagram_business_account")})
        return {"account_id": user.get("id", "meta-user"), "account_name": user.get("name", "Meta account"), "metadata": {"pages": pages}}

    def get_user_videos(self, connection: dict[str, Any]) -> list[dict[str, Any]]:
        token = connection["access_token"]
        account = connection.get("metadata") or self.get_account(token).get("metadata", {})
        result: list[dict[str, Any]] = []
        for page in account.get("pages", []):
            page_token = page.get("access_token") or token
            if self.meta.id == "facebook":
                data = self._get(f"https://graph.facebook.com/{GRAPH_VERSION}/{page.get('id')}/videos", page_token, {"fields": "id,description,created_time,thumbnail,source,length,permalink_url,views", "limit": 50})
                for item in data.get("data", []):
                    result.append({"id": item.get("id"), "title": item.get("description") or "Facebook video", "thumbnail_url": (item.get("thumbnail") or {}).get("uri"), "duration": item.get("length"), "created_at": item.get("created_time"), "platform": "Facebook", "views": item.get("views"), "media_url": item.get("source"), "page_id": page.get("id"), "media_import_available": bool(item.get("source")), "permalink": item.get("permalink_url")})
            else:
                ig = (page.get("instagram_business_account") or {}).get("id")
                if not ig: continue
                data = self._get(f"https://graph.facebook.com/{GRAPH_VERSION}/{ig}/media", page_token, {"fields": "id,caption,media_type,media_url,thumbnail_url,timestamp,permalink", "limit": 50})
                for item in data.get("data", []):
                    if item.get("media_type") not in {"VIDEO", "REELS"}: continue
                    result.append({"id": item.get("id"), "title": item.get("caption") or "Instagram video", "thumbnail_url": item.get("thumbnail_url"), "created_at": item.get("timestamp"), "platform": "Instagram", "media_url": item.get("media_url"), "page_id": page.get("id"), "media_import_available": bool(item.get("media_url")), "permalink": item.get("permalink")})
        return result

    def get_video_metadata(self, connection: dict[str, Any], video_id: str) -> dict[str, Any]:
        return self._get(f"https://graph.facebook.com/{GRAPH_VERSION}/{video_id}", connection["access_token"], {"fields": "id,description,created_time,thumbnail,source,length,permalink_url,views,media_url,media_type"})

    def get_video_media(self, connection: dict[str, Any], video: dict[str, Any]) -> dict[str, Any]:
        url = video.get("media_url") or video.get("source")
        if not url:
            return {"supported": False, "reason": f"{self.meta.name} did not provide an authorized media URL for this video. Upload the video file instead."}
        return {"supported": True, "url": url, "headers": {"Authorization": f"Bearer {connection['access_token']}"}}

    def publish_video(self, connection: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        if self.meta.id == "instagram":
            return {"supported": False, "reason": "Instagram publishing through the current API requires a publicly reachable video URL. Free Mode uses local storage only, so upload/download is available instead."}
        if "pages_manage_posts" not in connection.get("scopes", []):
            return {"supported": False, "reason": "Reconnect Facebook with the official pages_manage_posts permission before publishing."}
        pages = (connection.get("metadata") or {}).get("pages", [])
        page = next((item for item in pages if item.get("id") == payload.get("account_id")), pages[0] if pages else None)
        if not page:
            return {"supported": False, "reason": "No Facebook Page with publishing permission was returned by Meta."}
        path = Path(payload.get("local_path", ""))
        if not path.exists(): return {"supported": False, "reason": "The rendered clip is no longer available locally."}
        with path.open("rb") as handle:
            response = httpx.post(f"https://graph.facebook.com/{GRAPH_VERSION}/{page['id']}/videos", params={"access_token": page.get("access_token") or connection["access_token"]}, data={"description": payload.get("caption", "")}, files={"source": (path.name, handle, "video/mp4")}, timeout=600)
        if response.status_code >= 400: return {"supported": False, "reason": _friendly_http_error(response)}
        body = response.json()
        return {"supported": True, "published": True, "remote_id": body.get("id")}


class TikTokProvider(SocialPlatformProvider):
    meta = PlatformMeta(
        id="tiktok", name="TikTok", short_name="♪", color="#55e6e0",
        configured_env=("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET"),
        capabilities={"import_metadata": True, "import_media": False, "publish": True, "schedule": False},
        note="TikTok can expose account/video metadata and official posting when the app has approved scopes; it does not expose an authorized original-media download method here.",
    )

    def get_authorization_url(self, redirect_uri: str, state: str, purpose: str = "import") -> str:
        scopes = ["user.info.basic", "video.list"]
        if purpose == "publish": scopes.append("video.publish")
        return "https://www.tiktok.com/v2/auth/authorize/?" + urlencode({
            "client_key": os.getenv("TIKTOK_CLIENT_KEY"), "scope": ",".join(scopes), "response_type": "code", "redirect_uri": redirect_uri, "state": state,
        })

    def exchange_code(self, code: str, redirect_uri: str) -> dict[str, Any]:
        response = httpx.post("https://open.tiktokapis.com/v2/oauth/token/", data={
            "client_key": os.getenv("TIKTOK_CLIENT_KEY"), "client_secret": os.getenv("TIKTOK_CLIENT_SECRET"), "code": code, "grant_type": "authorization_code", "redirect_uri": redirect_uri,
        }, timeout=45)
        if response.status_code >= 400: raise RuntimeError(_friendly_http_error(response))
        return response.json()

    def get_account(self, access_token: str) -> dict[str, Any]:
        data = self._get("https://open.tiktokapis.com/v2/user/info/", access_token, {"fields": "open_id,display_name,avatar_url"})
        user = data.get("data", {}).get("user", {})
        return {"account_id": user.get("open_id", "tiktok-user"), "account_name": user.get("display_name", "TikTok account"), "metadata": {"avatar_url": user.get("avatar_url")}}

    def get_user_videos(self, connection: dict[str, Any]) -> list[dict[str, Any]]:
        data = self._post("https://open.tiktokapis.com/v2/video/list/", connection["access_token"], {"max_count": 20}, {"fields": "id,title,cover_image_url,share_url,create_time,duration,view_count,like_count,comment_count,share_count"})
        result = []
        for item in data.get("data", {}).get("videos", []):
            result.append({"id": item.get("id"), "title": item.get("title") or "TikTok video", "thumbnail_url": item.get("cover_image_url"), "duration": item.get("duration"), "created_at": _iso_from_epoch(item.get("create_time")), "platform": "TikTok", "views": item.get("view_count"), "media_import_available": False, "permalink": item.get("share_url")})
        return result

    def get_video_metadata(self, connection: dict[str, Any], video_id: str) -> dict[str, Any]:
        videos = self.get_user_videos(connection)
        return next((video for video in videos if video.get("id") == video_id), {"id": video_id, "platform": "TikTok"})

    def get_video_media(self, connection: dict[str, Any], video: dict[str, Any]) -> dict[str, Any]:
        return {"supported": False, "reason": "TikTok's current API does not provide an authorized original-video download method for this workflow. Upload the video file instead."}

    def publish_video(self, connection: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        if "video.publish" not in connection.get("scopes", []):
            return {"supported": False, "reason": "Reconnect TikTok with the official video.publish permission before publishing."}
        path = Path(payload.get("local_path", ""))
        if not path.exists(): return {"supported": False, "reason": "The rendered clip is no longer available locally."}
        size = path.stat().st_size
        body = {"post_info": {"title": payload.get("caption", "")[:150], "privacy_level": payload.get("visibility", "SELF_ONLY"), "disable_duet": False, "disable_comment": False, "disable_stitch": False}, "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": size, "total_chunk_count": 1}}
        init = httpx.post("https://open.tiktokapis.com/v2/post/publish/video/init/", headers={"Authorization": f"Bearer {connection['access_token']}", "Content-Type": "application/json; charset=UTF-8"}, json=body, timeout=60)
        if init.status_code >= 400: return {"supported": False, "reason": _friendly_http_error(init)}
        data = init.json().get("data", {})
        upload_url = data.get("upload_url")
        if not upload_url: return {"supported": False, "reason": "TikTok did not return an official upload URL."}
        upload = httpx.put(upload_url, headers={"Content-Type": "video/mp4", "Content-Range": f"bytes 0-{size-1}/{size}", "Content-Length": str(size)}, content=path.read_bytes(), timeout=600)
        if upload.status_code >= 400: return {"supported": False, "reason": _friendly_http_error(upload)}
        return {"supported": True, "published": True, "remote_id": data.get("publish_id")}


_PROVIDERS: dict[str, SocialPlatformProvider] = {
    "youtube": YouTubeProvider(),
    "facebook": MetaProvider("facebook"),
    "instagram": MetaProvider("instagram"),
    "tiktok": TikTokProvider(),
}


def get_provider(platform_id: str) -> SocialPlatformProvider:
    try:
        return _PROVIDERS[platform_id.lower()]
    except KeyError as exc:
        raise ValueError(f"Unsupported social platform: {platform_id}") from exc


def list_provider_metadata() -> list[dict[str, Any]]:
    return [{**provider.meta.__dict__, "configured": provider.is_configured()} for provider in _PROVIDERS.values()]
