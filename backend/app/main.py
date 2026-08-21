from __future__ import annotations

import html
import io
import json
import mimetypes
import os
import shutil
import uuid
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import auth_db, billing_db, content_db, db, social_db
from .auth_context import current_session_id, current_user_id, reset_context, set_context
from .auth_service import auth_payload, clear_session_cookie, frontend_redirect, public_user, rate_limit, session_user, set_session_cookie, validate_email, validate_password
from .ads import ad_manager
from .billing import billing_status, create_checkout, get_provider
from .billing_service import cancel_for_user, create_checkout_for_user, handle_webhook, pause_for_user, resume_for_user, verify_checkout_for_user
from .email_service import is_dev_link_allowed, password_reset_url, queue_and_deliver, verification_url
from .auth_oauth import authorization_url, complete as complete_oauth
from .config import (
    ALLOWED_EXTENSIONS,
    AUTH_REQUIRED,
    BLOCKED_URL_HOSTS,
    EMAIL_DELIVERY,
    ENVIRONMENT,
    FRONTEND_ORIGIN,
    MAX_FILE_SIZE_MB,
    MAX_VIDEO_DURATION,
    PRO_PRICE_MONTHLY,
    PUBLIC_API_URL,
    SESSION_COOKIE_NAME,
    TRIAL_DAYS,
    STORAGE_ROOT,
    ensure_storage,
    max_file_size_bytes,
    project_root,
)
from .services.content_generator import generate_content_pack
from .services.ffmpeg import FFmpegError, make_thumbnail, probe_video
from .services.pipeline import process_project_job, render_clip_job
from .services.publishing import publish_item, queue_clip_publish, retry_item
from .plans import current_plan, current_subscription, has_entitlement, list_plans
from .privacy import privacy_mode, privacy_status, set_privacy_mode
from .recovery import clear_project_clips, recover_interrupted_work
from .usage_service import available_daily_clips, available_daily_jobs, plan_interest, record as record_usage, usage
from .storage_guard import cleanup_expired_projects, ensure_capacity, storage_status
from .system_status import system_status
from .templates_catalog import get_template, list_templates
from .user_settings import get_user_settings, set_user_settings
from .services.social_service import (
    complete_connect,
    cost_status,
    free_mode,
    import_video as import_social_video,
    list_videos as list_social_videos,
    provider_status,
    set_free_mode,
    start_connect,
)

ensure_storage()
db.init_db()
auth_db.init_auth_db()
billing_db.init_billing_db()
recover_interrupted_work()
executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="viral-clip-worker")

app = FastAPI(title="ClipForge — Free AI Viral Clip Generator", version="0.1.0")
_cors_origins = [origin.strip() for origin in FRONTEND_ORIGIN.split(",") if origin.strip()] + ["http://localhost:5173", "http://127.0.0.1:5173"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(dict.fromkeys(_cors_origins)),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/media", StaticFiles(directory=str(STORAGE_ROOT)), name="media")

_PUBLIC_API_PATHS = ("/api/auth/", "/api/plans", "/api/health", "/api/billing/status", "/api/billing/webhook/", "/api/system/status")


@app.middleware("http")
async def authentication_middleware(request: Request, call_next: Any) -> Response:
    if request.method == "OPTIONS":
        return await call_next(request)
    client_ip = request.client.host if request.client else "unknown"
    rate_limited_path = request.url.path in {"/api/auth/login", "/api/auth/register", "/api/auth/forgot-password", "/api/auth/magic-link", "/api/billing/verify"}
    if rate_limited_path and not rate_limit(f"{client_ip}:{request.url.path}", 12, 900):
        return JSONResponse(status_code=429, content={"detail": "Too many attempts. Please wait and try again."})
    raw_session = request.cookies.get(SESSION_COOKIE_NAME)
    session = auth_db.get_session(raw_session)
    tokens = set_context(session["user_id"] if session else None, session["id"] if session else None)
    request.state.auth_session = session
    try:
        protected = request.url.path.startswith("/api/") or request.url.path.startswith("/media/")
        public = request.url.path.startswith(_PUBLIC_API_PATHS)
        if AUTH_REQUIRED and protected and not public and not session:
            return JSONResponse(status_code=401, content={"detail": "Authentication required."})
        state_changing = request.method in {"POST", "PUT", "PATCH", "DELETE"}
        csrf_exempt = request.url.path.startswith("/api/billing/webhook/") or request.url.path in {"/api/auth/register", "/api/auth/login", "/api/auth/logout", "/api/auth/verify-email", "/api/auth/forgot-password", "/api/auth/reset-password", "/api/auth/magic-link", "/api/auth/magic-link/consume"} or request.url.path.startswith("/api/auth/oauth/")
        if AUTH_REQUIRED and state_changing and protected and session and not csrf_exempt:
            csrf = request.headers.get("X-CSRF-Token")
            if not auth_db.verify_csrf(session["id"], csrf):
                return JSONResponse(status_code=403, content={"detail": "CSRF validation failed."})
        return await call_next(request)
    finally:
        reset_context(tokens)


class AuthRegisterRequest(BaseModel):
    email: str
    password: str
    name: str = ""
    remember_me: bool = False


class AuthLoginRequest(BaseModel):
    email: str
    password: str
    remember_me: bool = False


class AuthTokenRequest(BaseModel):
    token: str


class ResetPasswordRequest(BaseModel):
    token: str
    password: str


class ForgotPasswordRequest(BaseModel):
    email: str


class AuthProfileRequest(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=80)
    language: str | None = Field(default=None, max_length=12)
    timezone: str | None = Field(default=None, max_length=80)
    theme: str | None = Field(default=None, max_length=20)
    notification_preferences: dict[str, bool] | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class MagicLinkRequest(BaseModel):
    email: str


class BillingVerifyRequest(BaseModel):
    razorpay_order_id: str | None = None
    razorpay_payment_id: str | None = None
    razorpay_subscription_id: str | None = None
    razorpay_signature: str | None = None


class BillingCancelRequest(BaseModel):
    cancel_at_cycle_end: bool = True


class BillingRefundRequest(BaseModel):
    amount_inr: int | None = Field(default=None, ge=1)
    reason: str = Field(default="Customer requested refund", max_length=300)


class ProjectCreate(BaseModel):
    name: str = Field(default="Untitled project", min_length=1, max_length=120)
    rights_acknowledged: bool = False


class ImportURL(BaseModel):
    url: str = Field(min_length=8, max_length=2048)


class ClipUpdate(BaseModel):
    start_sec: float | None = Field(default=None, ge=0)
    end_sec: float | None = Field(default=None, gt=0)
    captions_enabled: bool | None = None
    caption_style: str | None = None
    caption_font_size: int | None = Field(default=None, ge=18, le=72)
    caption_position: str | None = None
    hook_enabled: bool | None = None
    hook: str | None = Field(default=None, max_length=180)
    hook_position: str | None = None
    hook_duration: float | None = Field(default=None, ge=0.5, le=8)
    format: str | None = None
    logo_path: str | None = None
    logo_position: str | None = None
    logo_opacity: float | None = Field(default=None, ge=0.05, le=1)
    intro_text: str | None = Field(default=None, max_length=120)
    outro_text: str | None = Field(default=None, max_length=120)
    intro_duration: float | None = Field(default=None, ge=0.2, le=5)
    outro_duration: float | None = Field(default=None, ge=0.2, le=5)
    music_path: str | None = None
    music_volume: float | None = Field(default=None, ge=0, le=1)
    sfx_path: str | None = None
    sfx_volume: float | None = Field(default=None, ge=0, le=1)
    speed: float | None = Field(default=None, ge=0.5, le=2)
    effects: dict[str, Any] | None = None


class RenderRequest(BaseModel):
    pass


class SocialImportRequest(BaseModel):
    connection_id: str
    video_id: str
    project_name: str = Field(default="Imported social video", max_length=120)
    rights_acknowledged: bool = False


class FreeModeRequest(BaseModel):
    free_mode: bool


class PublishRequest(BaseModel):
    clip_id: str
    platform: str
    account_id: str | None = None
    caption: str = Field(default="", max_length=2200)
    title: str = Field(default="", max_length=150)
    hashtags: list[str] = Field(default_factory=list, max_length=30)
    visibility: str = "private"
    scheduled_at: str | None = None
    rights_acknowledged: bool = False


class ContentPackRegenerateRequest(BaseModel):
    language: str = "en"
    tone: str = "casual"
    variant: int = Field(default=0, ge=0, le=20)


class AdEventRequest(BaseModel):
    ad_id: str = Field(min_length=1, max_length=120)
    page: str = Field(default="unknown", max_length=80)
    device: str = Field(default="desktop", max_length=30)


class UserSettingsRequest(BaseModel):
    language: str = "en"
    default_clip_length: int = 30
    default_aspect: str = "9:16"
    caption_style: str = "bold"
    caption_position: str = "bottom"
    hook_style: str = "curiosity"
    hashtag_count: int = 10
    default_platform: str = "youtube_shorts"
    tone: str = "casual"
    brand_name: str = ""
    brand_description: str = ""


class ThumbnailRequest(BaseModel):
    time_offset: float = Field(default=0.5, ge=0, le=60)
    text: str = Field(default="", max_length=120)
    position: str = "bottom"


class PlanInterestRequest(BaseModel):
    plan_id: str
    contact: str = ""
    note: str = ""


class PrivacyRequest(BaseModel):
    enabled: bool


class CheckoutRequest(BaseModel):
    plan_id: str = "pro"


class TemplateApplyRequest(BaseModel):
    template_id: str


VIDEO_MIME_TYPES = {
    "video/mp4", "video/quicktime", "video/x-matroska", "video/webm", "video/x-msvideo", "application/octet-stream"
}


def _media_url(path: str | None) -> str | None:
    if not path:
        return None
    try:
        relative = Path(path).resolve().relative_to(STORAGE_ROOT.resolve())
        relative_url = "/media/" + relative.as_posix()
        return f"{PUBLIC_API_URL.rstrip('/')}{relative_url}" if PUBLIC_API_URL else relative_url
    except Exception:
        return None


def _project_response(project: dict[str, Any] | None) -> dict[str, Any] | None:
    if not project:
        return None
    result = dict(project)
    result["rights_acknowledged"] = bool(result.get("rights_acknowledged"))
    result["original_url"] = _media_url(result.get("original_path"))
    result["clips"] = [_clip_response(clip) for clip in db.list_clips(result["id"])]
    packs = content_db.list_content_packs(result["id"])
    result["content_packs"] = packs if has_entitlement("full_content_pack") else []
    clip_scores = [float(clip.get("score", 0)) for clip in db.list_clips(result["id"])]
    result["summary"] = {
        "duration": result.get("duration"), "highlights_found": len(result["clips"]),
        "top_clips_generated": sum(1 for clip in result["clips"] if clip and clip.get("status") == "ready"),
        "average_score": round(sum(clip_scores) / len(clip_scores), 1) if clip_scores else 0,
        "content_packs_generated": len(packs), "seo_packages_generated": sum(1 for pack in packs if pack.get("data", {}).get("seo")),
    }
    return result


def _clip_response(clip: dict[str, Any] | None) -> dict[str, Any] | None:
    if not clip:
        return None
    result = dict(clip)
    result["video_url"] = _media_url(result.get("video_path"))
    result["thumbnail_url"] = _media_url(result.get("thumbnail_path"))
    pack = content_db.get_content_pack(result["id"])
    result["content_pack"] = pack.get("data") if pack and has_entitlement("full_content_pack") else None
    result["content_pack_locked"] = bool(pack and not has_entitlement("full_content_pack"))
    result.pop("video_path", None)
    result.pop("thumbnail_path", None)
    return result


def _safe_suffix(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported video format. Use MP4, MOV, MKV, WebM, or AVI.")
    return suffix


def _validate_rights(project: dict[str, Any]) -> None:
    if not project.get("rights_acknowledged"):
        raise HTTPException(status_code=400, detail="Please confirm that you own or have permission to use this video.")


def _save_upload(upload: UploadFile, destination: Path) -> int:
    size = 0
    try:
        ensure_capacity(int(getattr(upload, "size", 0) or 0))
    except RuntimeError as exc:
        raise HTTPException(status_code=507, detail=str(exc))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as output:
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > max_file_size_bytes():
                output.close()
                destination.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail=f"Video is larger than the {MAX_FILE_SIZE_MB} MB free-mode limit.")
            output.write(chunk)
    return size


def _invoice_pdf(invoice: dict[str, Any], user: dict[str, Any]) -> bytes:
    def esc(value: Any) -> str:
        return str(value).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")[:180]
    lines = [
        ("ClipForge Invoice", 18),
        (f"Invoice number: {invoice.get('invoice_number', '')}", 11),
        (f"Date: {invoice.get('invoice_date', '')}", 11),
        (f"Customer: {user.get('name') or user.get('email', '')}", 11),
        (f"Email: {user.get('email', '')}", 11),
        (f"Plan: {invoice.get('plan_id', 'pro').title()}", 11),
        (f"Amount: INR {int(invoice.get('amount', 0))}", 11),
        (f"Tax: INR {int(invoice.get('tax', 0))}", 11),
        (f"Status: {invoice.get('status', 'paid')}", 11),
        (f"Payment method: {invoice.get('payment_method') or 'Provider checkout'}", 11),
        ("This invoice was generated by ClipForge after server-side payment verification.", 10),
    ]
    stream_lines = ["BT", "50 780 Td"]
    for index, (text, size) in enumerate(lines):
        if index:
            stream_lines.append("0 -28 Td")
        stream_lines.append(f"/F1 {size} Tf ({esc(text)}) Tj")
    stream_lines.append("ET")
    stream = "\\n".join(stream_lines).encode("latin-1", "replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\\nstream\\n" + stream + b"\\nendstream",
    ]
    result = bytearray(b"%PDF-1.4\\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(result))
        result.extend(f"{index} 0 obj\\n".encode())
        result.extend(obj)
        result.extend(b"\\nendobj\\n")
    xref = len(result)
    result.extend(f"xref\\n0 {len(objects) + 1}\\n0000000000 65535 f \\n".encode())
    for offset in offsets[1:]:
        result.extend(f"{offset:010d} 00000 n \\n".encode())
    result.extend(f"trailer\\n<< /Size {len(objects) + 1} /Root 1 0 R >>\\nstartxref\\n{xref}\\n%%EOF\\n".encode())
    return bytes(result)


def _validate_video(path: Path) -> dict[str, Any]:
    try:
        metadata = probe_video(path)
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"The uploaded file is not a readable video: {str(exc)[-240:]}")
    if metadata["duration"] <= 0:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="The video duration could not be detected.")
    if metadata["duration"] > MAX_VIDEO_DURATION:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=413, detail=f"Free mode supports videos up to {MAX_VIDEO_DURATION // 60} minutes.")
    return metadata


def _require_user(request: Request) -> dict[str, Any]:
    session = session_user(request)
    if not session:
        raise HTTPException(status_code=401, detail="Authentication required.")
    user = auth_db.get_user(session["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="Account session is no longer valid.")
    return user


def _auth_response(user: dict[str, Any], session: dict[str, Any], status_code: int = 200, extra: dict[str, Any] | None = None) -> JSONResponse:
    session["remember_me"] = bool(session.get("remember_me"))
    payload = auth_payload(user, session)
    if extra:
        payload.update(extra)
    response = JSONResponse(status_code=status_code, content=payload)
    set_session_cookie(response, session)
    return response


@app.get("/api/auth/me")
def auth_me(request: Request) -> dict[str, Any]:
    session = session_user(request)
    if not session:
        return {"authenticated": False, "user": None}
    user = auth_db.get_user(session["user_id"])
    if not user:
        return {"authenticated": False, "user": None}
    return auth_payload(user, {"session_id": session["id"], "csrf_token": session["csrf_token"], "expires_at": session["expires_at"]})


@app.post("/api/auth/register")
def auth_register(body: AuthRegisterRequest, request: Request) -> JSONResponse:
    try:
        email = validate_email(body.email)
        password = validate_password(body.password)
        user = auth_db.create_user(email, password, body.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise HTTPException(status_code=409, detail="An account with this email already exists.")
        raise HTTPException(status_code=400, detail="Could not create the account.")
    if TRIAL_DAYS > 0:
        trial_start = datetime.now(timezone.utc)
        trial_end = trial_start + timedelta(days=TRIAL_DAYS)
        billing_db.upsert_subscription(user["id"], "local", f"trial:{user['id']}", "pro", "trial", current_start=trial_start.isoformat(), current_end=trial_end.isoformat(), renewal_at=trial_end.isoformat(), payload={"trial_days": TRIAL_DAYS})
        user = auth_db.update_user(user["id"], plan_id="pro") or user
    token = auth_db.create_one_time_token(user["id"], "verify_email", hours=24)
    link = verification_url(token)
    email_result = queue_and_deliver(user["id"], user["email"], "verification", "Verify your ClipForge email", f"Welcome to ClipForge. Verify your email here:\n\n{link}\n\nThis link expires in 24 hours.")
    session = auth_db.create_session(user["id"], request.headers.get("user-agent", ""), request.client.host if request.client else "", body.remember_me)
    extra: dict[str, Any] = {"email_verification_required": True, "email_delivery": email_result["status"]}
    if is_dev_link_allowed():
        extra["verification_link"] = link
    return _auth_response(auth_db.get_user(user["id"]) or user, session, 201, extra)


@app.post("/api/auth/login")
def auth_login(body: AuthLoginRequest, request: Request) -> JSONResponse:
    try:
        email = validate_email(body.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    user = auth_db.get_user_by_email(email)
    if not user or not auth_db.verify_password(body.password, user.get("password_hash")):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    session = auth_db.create_session(user["id"], request.headers.get("user-agent", ""), request.client.host if request.client else "", body.remember_me)
    response = _auth_response(auth_db.get_user(user["id"]) or user, session)
    return response


@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response) -> dict[str, bool]:
    session = session_user(request)
    if session:
        auth_db.revoke_session(session["id"])
    clear_session_cookie(response)
    return {"ok": True}


@app.post("/api/auth/verify-email")
def auth_verify_email(body: AuthTokenRequest) -> dict[str, Any]:
    token = auth_db.consume_one_time_token(body.token, "verify_email")
    if not token:
        raise HTTPException(status_code=400, detail="Verification link is invalid or expired.")
    user = auth_db.update_user(token["user_id"], email_verified=1)
    return {"verified": True, "user": public_user(user), "message": "Email verified. You can use your ClipForge account."}


@app.get("/api/auth/dev/outbox")
def auth_dev_outbox(request: Request) -> dict[str, Any]:
    if not is_dev_link_allowed():
        raise HTTPException(status_code=404, detail="Not found.")
    user = _require_user(request)
    return {"messages": auth_db.list_email_outbox(user["id"])}


@app.post("/api/auth/forgot-password")
def auth_forgot_password(body: ForgotPasswordRequest) -> dict[str, Any]:
    response: dict[str, Any] = {"ok": True, "message": "If an account exists, password reset instructions have been sent."}
    try:
        email = validate_email(body.email)
    except ValueError:
        return response
    user = auth_db.get_user_by_email(email)
    if not user:
        return response
    token = auth_db.create_one_time_token(user["id"], "reset_password", hours=2)
    link = password_reset_url(token)
    result = queue_and_deliver(user["id"], user["email"], "password_reset", "Reset your ClipForge password", f"Reset your password here:\n\n{link}\n\nThis link expires in 2 hours.")
    response["email_delivery"] = result["status"]
    if is_dev_link_allowed():
        response["reset_link"] = link
    return response


@app.post("/api/auth/reset-password")
def auth_reset_password(body: ResetPasswordRequest) -> dict[str, Any]:
    token = auth_db.consume_one_time_token(body.token, "reset_password")
    if not token:
        raise HTTPException(status_code=400, detail="Reset link is invalid or expired.")
    auth_db.change_password(token["user_id"], validate_password(body.password))
    return {"ok": True, "message": "Password changed. Please log in again on your devices."}


@app.post("/api/auth/magic-link")
def auth_magic_link(body: MagicLinkRequest) -> dict[str, Any]:
    response: dict[str, Any] = {"ok": True, "message": "If an account exists, a sign-in link has been sent."}
    try:
        email = validate_email(body.email)
    except ValueError:
        return response
    user = auth_db.get_user_by_email(email)
    if user:
        token = auth_db.create_one_time_token(user["id"], "magic_link", hours=1)
        link = f"{FRONTEND_ORIGIN.rstrip('/')}/magic-login?token={token}"
        result = queue_and_deliver(user["id"], email, "magic_link", "Your ClipForge sign-in link", f"Sign in to ClipForge here:\n\n{link}\n\nThis link expires in 1 hour.")
        response["email_delivery"] = result["status"]
        if is_dev_link_allowed():
            response["magic_link"] = link
    return response


@app.post("/api/auth/magic-link/consume")
def auth_magic_link_consume(body: AuthTokenRequest, request: Request) -> JSONResponse:
    token = auth_db.consume_one_time_token(body.token, "magic_link")
    if not token:
        raise HTTPException(status_code=400, detail="Magic link is invalid or expired.")
    user = auth_db.update_user(token["user_id"], email_verified=1)
    session = auth_db.create_session(user["id"], request.headers.get("user-agent", ""), request.client.host if request.client else "", True)
    return _auth_response(user, session)


@app.get("/api/auth/oauth/{provider}/start")
def auth_oauth_start(provider: str) -> dict[str, str]:
    redirect_uri = f"{FRONTEND_ORIGIN.rstrip('/')}/api/auth/oauth/{provider}/callback"
    try:
        return {"provider": provider, "url": authorization_url(provider, redirect_uri)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/auth/oauth/{provider}/callback")
def auth_oauth_callback(provider: str, code: str | None = None, state: str | None = None, error: str | None = None) -> Response:
    if error:
        return RedirectResponse(frontend_redirect(f"/app?auth_error={error[:120]}"))
    if not code or not state:
        return RedirectResponse(frontend_redirect("/app?auth_error=OAuth response was incomplete"))
    try:
        user = complete_oauth(provider, code, state)
        session = auth_db.create_session(user["id"], "OAuth", "", True)
        response = RedirectResponse(frontend_redirect("/app?auth=success"))
        set_session_cookie(response, session)
        return response
    except Exception:
        return RedirectResponse(frontend_redirect("/app?auth_error=OAuth sign-in failed"))


@app.get("/api/auth/profile")
def auth_profile(request: Request) -> dict[str, Any]:
    return {"user": public_user(_require_user(request))}


@app.put("/api/auth/profile")
def auth_update_profile(body: AuthProfileRequest, request: Request) -> dict[str, Any]:
    user = _require_user(request)
    changes = body.model_dump(exclude_unset=True)
    updated = auth_db.update_user(user["id"], **changes)
    return {"user": public_user(updated)}


@app.post("/api/auth/profile/photo")
def auth_profile_photo(request: Request, file: UploadFile = File(...)) -> dict[str, Any]:
    user = _require_user(request)
    suffix = Path(file.filename or "profile.jpg").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(status_code=400, detail="Profile photo must be PNG, JPG, JPEG, or WebP.")
    destination = STORAGE_ROOT / "users" / user["id"] / f"profile{suffix}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    _save_upload(file, destination)
    updated = auth_db.update_user(user["id"], profile_photo_path=str(destination))
    return {"user": public_user(updated)}


@app.post("/api/auth/password")
def auth_change_password(body: ChangePasswordRequest, request: Request) -> dict[str, Any]:
    user = _require_user(request)
    if not auth_db.verify_password(body.current_password, user.get("password_hash")):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    auth_db.change_password(user["id"], validate_password(body.new_password))
    return {"ok": True, "message": "Password changed. Other sessions were revoked."}


@app.get("/api/auth/sessions")
def auth_sessions(request: Request) -> dict[str, Any]:
    return {"sessions": auth_db.list_sessions(_require_user(request)["id"]), "current_session_id": current_session_id()}


@app.delete("/api/auth/sessions/{session_id}")
def auth_revoke_session(session_id: str, request: Request) -> dict[str, bool]:
    user = _require_user(request)
    allowed = {item["id"] for item in auth_db.list_sessions(user["id"])}
    if session_id not in allowed:
        raise HTTPException(status_code=404, detail="Session not found.")
    auth_db.revoke_session(session_id)
    return {"ok": True}


def _require_admin(request: Request) -> dict[str, Any]:
    user = _require_user(request)
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Administrator access required.")
    return user


@app.get("/api/admin/overview")
def admin_overview(request: Request) -> dict[str, Any]:
    _require_admin(request)
    conn = db.connect()
    try:
        users = conn.execute("SELECT COUNT(*) AS total, SUM(CASE WHEN plan_id='free' THEN 1 ELSE 0 END) AS free_users, SUM(CASE WHEN plan_id='pro' THEN 1 ELSE 0 END) AS pro_users FROM users").fetchone()
        revenue = conn.execute("SELECT COALESCE(SUM(amount),0) AS total FROM billing_payments WHERE status='captured'").fetchone()["total"] if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='billing_payments'").fetchone() else 0
        subscriptions = conn.execute("SELECT status, COUNT(*) AS count FROM billing_subscriptions GROUP BY status").fetchall() if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='billing_subscriptions'").fetchone() else []
        signups = conn.execute("SELECT substr(created_at,1,10) AS day, COUNT(*) AS count FROM users GROUP BY day ORDER BY day DESC LIMIT 30").fetchall()
        countries = conn.execute("SELECT country, COUNT(*) AS count FROM users WHERE country <> '' GROUP BY country ORDER BY count DESC LIMIT 20").fetchall()
        usage_rows = conn.execute("SELECT event_type, COALESCE(SUM(amount),0) AS amount FROM usage_events GROUP BY event_type").fetchall()
    finally:
        conn.close()
    users_payload = dict(users) if users else {}
    total_users = int(users_payload.get("total") or 0)
    pro_users = int(users_payload.get("pro_users") or 0)
    active_count = sum(int(row["count"]) for row in subscriptions if row["status"] in {"active", "authenticated", "trial"})
    cancelled_count = sum(int(row["count"]) for row in subscriptions if row["status"] in {"cancelled", "expired", "failed"})
    mrr = active_count * PRO_PRICE_MONTHLY
    return {"users": users_payload, "revenue_inr": int(revenue or 0), "subscriptions": [dict(row) for row in subscriptions], "daily_signups": [dict(row) for row in signups], "top_countries": [dict(row) for row in countries], "processing_usage": [dict(row) for row in usage_rows], "analytics": {"mrr_inr": mrr, "arr_inr": mrr * 12, "conversion_rate": round(pro_users / total_users * 100, 2) if total_users else 0, "churn_rate": round(cancelled_count / (active_count + cancelled_count) * 100, 2) if active_count + cancelled_count else 0}}


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "clipforge", "ffmpeg": "configured", "mode": "local-open-source"}


@app.get("/api/ads/config")
def ads_config() -> dict[str, Any]:
    return ad_manager.config()


@app.get("/api/ads/next")
def next_ad(session_id: str, page: str = "dashboard", device: str = "desktop") -> dict[str, Any]:
    ad = ad_manager.get_ad(session_id, page, device)
    return {"show": bool(ad), "ad": ad}


@app.post("/api/ads/impression")
def ad_impression(body: AdEventRequest) -> dict[str, bool]:
    ad_manager.record_impression(body.ad_id, body.page, body.device)
    return {"ok": True}


@app.post("/api/ads/click")
def ad_click(body: AdEventRequest) -> dict[str, bool]:
    ad_manager.record_click(body.ad_id, body.page, body.device)
    return {"ok": True}


@app.get("/api/ads/metrics")
def ads_metrics() -> dict[str, Any]:
    return ad_manager.metrics_snapshot()


@app.get("/api/social/providers")
def social_providers() -> dict[str, Any]:
    return {"free_mode": free_mode(), "providers": provider_status()}


@app.get("/api/social/connections")
def social_connections() -> dict[str, Any]:
    return {"connections": social_db.list_connections()}


@app.get("/api/social/{platform}/connect")
def social_connect(platform: str, purpose: str = "import", redirect_uri: str | None = None) -> dict[str, Any]:
    if purpose not in {"import", "publish"}:
        raise HTTPException(status_code=400, detail="Purpose must be import or publish.")
    callback = redirect_uri or os.getenv("SOCIAL_OAUTH_REDIRECT_URI") or "http://localhost:5173/api/social/oauth/callback"
    try:
        return start_connect(platform, purpose, callback)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/social/oauth/callback", response_class=HTMLResponse)
def social_oauth_callback(platform: str, code: str | None = None, state: str | None = None, error: str | None = None) -> str:
    safe_platform = html.escape(platform.title())
    if error:
        message = html.escape(error[:700])
        return f"""<!doctype html><html><body><h2>Connection cancelled</h2><p>{message}</p><p>You can close this window.</p><script>window.opener?.postMessage({{type:'clipforge-oauth',platform:'{html.escape(platform)}',ok:false}}, window.location.origin);</script></body></html>"""
    if not code or not state:
        return "<!doctype html><html><body><h2>Connection incomplete</h2><p>The platform did not return an authorization code.</p><script>window.opener?.postMessage({type:'clipforge-oauth',ok:false}, window.location.origin);</script></body></html>"
    try:
        result = complete_connect(platform, code, state)
        account = html.escape(result["connection"]["account_name"])
        return f"""<!doctype html><html><body><h2>{safe_platform} connected</h2><p>Account: {account}</p><p>This window will close automatically.</p><script>window.opener?.postMessage({{type:'clipforge-oauth',platform:'{html.escape(platform)}',ok:true}}, window.location.origin); setTimeout(() => window.close(), 700);</script></body></html>"""
    except Exception as exc:
        message = html.escape(str(exc)[:700])
        return f"""<!doctype html><html><body><h2>Connection failed</h2><p>{message}</p><p>No password or pasted token was stored.</p><script>window.opener?.postMessage({{type:'clipforge-oauth',platform:'{html.escape(platform)}',ok:false}}, window.location.origin);</script></body></html>"""


@app.delete("/api/social/connections/{connection_id}")
def disconnect_social(connection_id: str) -> dict[str, bool]:
    if not social_db.get_connection(connection_id):
        raise HTTPException(status_code=404, detail="Connection not found")
    social_db.delete_connection(connection_id)
    return {"ok": True}


@app.get("/api/social/{platform}/videos")
def social_videos(platform: str, connection_id: str) -> dict[str, Any]:
    try:
        return {"platform": platform, "videos": list_social_videos(platform, connection_id)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/social/{platform}/import")
def social_import(platform: str, body: SocialImportRequest) -> dict[str, Any]:
    if not body.rights_acknowledged:
        raise HTTPException(status_code=400, detail="Confirm that you own or have authorization to edit and publish this content.")
    try:
        videos = list_social_videos(platform, body.connection_id)
        selected = next((video for video in videos if str(video.get("id")) == str(body.video_id)), None)
        if not selected:
            raise RuntimeError("That video was not found in the connected account.")
        project = import_social_video(platform, body.connection_id, selected, body.project_name, body.rights_acknowledged)
        return {"project": _project_response(project)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/cost-status")
def get_cost_status() -> dict[str, Any]:
    return cost_status()


@app.get("/api/storage/status")
def get_storage_status() -> dict[str, Any]:
    return storage_status()


@app.post("/api/storage/cleanup")
def cleanup_storage() -> dict[str, Any]:
    return cleanup_expired_projects()


@app.get("/api/plans")
def get_plans_endpoint() -> dict[str, Any]:
    status = billing_status()
    return {"plans": list_plans(), "billing_configured": bool(status.get("configured")), "provider": status.get("provider"), "note": "Prices are a catalog. A plan activates only after server-side provider verification."}


@app.get("/api/subscription")
def get_subscription_endpoint() -> dict[str, Any]:
    return current_subscription()


@app.get("/api/billing/status")
def billing_status_endpoint() -> dict[str, Any]:
    return billing_status()


@app.post("/api/billing/checkout")
def billing_checkout_endpoint(body: CheckoutRequest, request: Request) -> dict[str, Any]:
    user = _require_user(request)
    try:
        return create_checkout_for_user(user["id"], body.plan_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)[-400:])


@app.post("/api/billing/verify")
def billing_verify_endpoint(body: BillingVerifyRequest, request: Request) -> dict[str, Any]:
    user = _require_user(request)
    try:
        return verify_checkout_for_user(user["id"], body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)[-400:])


@app.post("/api/billing/webhook/razorpay")
async def razorpay_webhook(request: Request) -> dict[str, Any]:
    raw_body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")
    event_id = request.headers.get("x-razorpay-event-id")
    try:
        return handle_webhook("razorpay", raw_body, signature, event_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)[-400:])


@app.get("/api/billing/dashboard")
def billing_dashboard(request: Request) -> dict[str, Any]:
    user = _require_user(request)
    subscription = billing_db.get_current_subscription(user["id"])
    return {"user": public_user(user), "subscription": subscription, "payments": billing_db.list_payments(user["id"]), "invoices": billing_db.list_invoices(user["id"]), "provider": billing_status()}


@app.post("/api/billing/subscription/cancel")
def billing_cancel(body: BillingCancelRequest, request: Request) -> dict[str, Any]:
    user = _require_user(request)
    subscription = billing_db.get_current_subscription(user["id"])
    if not subscription or subscription.get("provider_subscription_id", "").startswith("order:"):
        raise HTTPException(status_code=400, detail="This account does not have a cancellable recurring subscription.")
    try:
        return cancel_for_user(user["id"], subscription["provider_subscription_id"], body.cancel_at_cycle_end)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)[-400:])


@app.post("/api/billing/subscription/pause")
def billing_pause(request: Request) -> dict[str, Any]:
    try:
        return pause_for_user(_require_user(request)["id"])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)[-400:])


@app.post("/api/billing/subscription/resume")
def billing_resume(request: Request) -> dict[str, Any]:
    try:
        return resume_for_user(_require_user(request)["id"])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)[-400:])


@app.post("/api/billing/payments/{payment_id}/refund")
def billing_refund(payment_id: str, body: BillingRefundRequest, request: Request) -> dict[str, Any]:
    _require_admin(request)
    payment = billing_db.get_payment(payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found.")
    provider = get_provider(payment["provider"])
    try:
        result = provider.refund(payment["provider_payment_id"], body.amount_inr, {"reason": body.reason})
        updated = billing_db.update_payment(payment_id, status="refunded", provider_payload=result)
        return {"payment": updated, "provider": result, "message": "Refund request sent to the official provider."}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)[-400:])


@app.get("/api/billing/invoices/{invoice_id}/download")
def billing_invoice_download(invoice_id: str, request: Request) -> Response:
    user = _require_user(request)
    invoice = billing_db.get_invoice(invoice_id)
    if not invoice or invoice["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    pdf = _invoice_pdf(invoice, user)
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename={invoice['invoice_number']}.pdf"})


@app.get("/api/usage")
def get_usage_endpoint() -> dict[str, Any]:
    return usage()


@app.post("/api/subscription/interest")
def plan_interest_endpoint(body: PlanInterestRequest) -> dict[str, Any]:
    try:
        return plan_interest(body.plan_id, body.contact, body.note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    return {"free_mode": free_mode()}


@app.put("/api/settings")
def update_settings(body: FreeModeRequest) -> dict[str, Any]:
    return {"free_mode": set_free_mode(body.free_mode)}


@app.get("/api/user-settings")
def get_user_settings_endpoint() -> dict[str, Any]:
    return {"settings": get_user_settings()}


@app.put("/api/user-settings")
def update_user_settings_endpoint(body: UserSettingsRequest) -> dict[str, Any]:
    return {"settings": set_user_settings(body.model_dump())}


@app.get("/api/privacy")
def get_privacy_endpoint() -> dict[str, Any]:
    return privacy_status()


@app.put("/api/privacy")
def update_privacy_endpoint(body: PrivacyRequest) -> dict[str, Any]:
    return {"enabled": set_privacy_mode(body.enabled), "status": privacy_status()}


@app.get("/api/publishing/queue")
def publishing_queue() -> dict[str, Any]:
    return {"items": social_db.list_publish_items()}


@app.post("/api/publishing/queue")
def add_to_publishing_queue(body: PublishRequest) -> dict[str, Any]:
    try:
        item = queue_clip_publish(
            body.clip_id, body.platform, body.account_id, body.caption, body.title, body.hashtags,
            body.visibility, body.scheduled_at, body.rights_acknowledged,
        )
        return {"item": item, "message": "Ready to publish. Nothing has been posted yet."}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/publishing/queue/{item_id}/publish")
def publish_queue_item(item_id: str) -> dict[str, Any]:
    try:
        return {"item": publish_item(item_id)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/publishing/queue/{item_id}/retry")
def retry_publishing_item(item_id: str) -> dict[str, Any]:
    try:
        return {"item": retry_item(item_id)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/api/publishing/queue/{item_id}")
def delete_publishing_item(item_id: str) -> dict[str, bool]:
    if not social_db.get_publish_item(item_id):
        raise HTTPException(status_code=404, detail="Publishing item not found")
    social_db.delete_publish_item(item_id)
    return {"ok": True}


@app.get("/api/stats")
def stats() -> dict[str, Any]:
    projects = db.list_projects(limit=10000)
    clips = sum(int(item.get("clip_count", 0)) for item in projects)
    ready = sum(int(item.get("ready_count", 0)) for item in projects)
    durations = [float(item["processing_ms"]) for item in projects if item.get("processing_ms") is not None]
    return {
        "projects": len(projects), "clips": clips, "ready_clips": ready,
        "videos_processed": sum(1 for item in projects if item.get("status") == "finished"),
        "avg_processing_seconds": round(sum(durations) / len(durations) / 1000, 1) if durations else None,
    }


@app.get("/api/system/status")
def system_status_endpoint() -> dict[str, Any]:
    return system_status()


@app.get("/api/queue")
def processing_queue() -> dict[str, Any]:
    active_statuses = {"preparing", "transcribing", "detecting_scenes", "detecting_highlights", "scoring_moments", "creating_clips", "adding_captions", "generating_content", "seo_analysis"}
    active_projects = [
        {key: project.get(key) for key in ("id", "name", "status", "progress", "current_stage", "created_at")}
        for project in db.list_projects(limit=100)
        if project.get("status") in active_statuses
    ]
    conn = db.connect()
    try:
        render_rows = conn.execute("SELECT id, project_id, clip_id, status, progress, message, updated_at FROM render_jobs WHERE status IN ('queued','rendering') ORDER BY updated_at DESC LIMIT 50").fetchall()
        render_jobs = [dict(row) for row in render_rows]
    finally:
        conn.close()
    return {"projects": active_projects, "render_jobs": render_jobs, "active": bool(active_projects or render_jobs)}


@app.get("/api/projects")
def projects() -> list[dict[str, Any]]:
    return db.list_projects()


@app.post("/api/projects")
def create_project(body: ProjectCreate) -> dict[str, Any]:
    if not body.rights_acknowledged:
        raise HTTPException(status_code=400, detail="Rights acknowledgement is required before processing content.")
    project = db.create_project(body.name, True)
    project_root(project["id"])
    return _project_response(project)  # type: ignore[return-value]


@app.get("/api/projects/{project_id}")
def get_project(project_id: str) -> dict[str, Any]:
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return _project_response(project)  # type: ignore[return-value]


@app.delete("/api/projects/{project_id}")
def delete_project_endpoint(project_id: str) -> dict[str, bool]:
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    shutil.rmtree(project_root(project_id), ignore_errors=True)
    db.delete_project(project_id)
    return {"ok": True}


@app.get("/api/projects/{project_id}/status")
def project_status(project_id: str) -> dict[str, Any]:
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {
        "id": project_id,
        "status": project["status"],
        "progress": project["progress"],
        "current_stage": project["current_stage"],
        "error": project.get("error"),
        "clip_count": len(db.list_clips(project_id)),
    }


@app.post("/api/projects/{project_id}/upload")
def upload_video(project_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    _validate_rights(project)
    suffix = _safe_suffix(file.filename)
    root = project_root(project_id)
    destination = root / f"original{suffix}"
    size = _save_upload(file, destination)
    metadata = _validate_video(destination)
    db.update_project(
        project_id, original_path=str(destination), source_type="upload", original_filename=Path(file.filename or "video").name,
        status="uploaded", progress=0, current_stage="Ready to analyze", error=None, **metadata
    )
    return {"project": _project_response(db.get_project(project_id)), "size_bytes": size}


@app.post("/api/projects/{project_id}/import-url")
def import_video_url(project_id: str, body: ImportURL) -> dict[str, Any]:
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    _validate_rights(project)
    if privacy_mode():
        raise HTTPException(status_code=400, detail="Privacy Mode is on. Upload the video file locally; external URL requests are disabled.")
    parsed = urlparse(body.url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or not host:
        raise HTTPException(status_code=400, detail="Enter a valid HTTPS video file URL.")
    if host in BLOCKED_URL_HOSTS or any(host.endswith("." + blocked) for blocked in BLOCKED_URL_HOSTS):
        raise HTTPException(status_code=400, detail="This source looks like a platform page. Upload a video file instead; ClipForge does not download platform pages.")
    root = project_root(project_id)
    destination = root / "original.mp4"
    try:
        with httpx.Client(follow_redirects=True, timeout=60) as client:
            with client.stream("GET", body.url) as response:
                response.raise_for_status()
                final_host = (urlparse(str(response.url)).hostname or "").lower()
                if final_host in BLOCKED_URL_HOSTS or any(final_host.endswith("." + blocked) for blocked in BLOCKED_URL_HOSTS):
                    raise HTTPException(status_code=400, detail="The URL redirected to a platform page. Upload the file instead.")
                content_type = response.headers.get("content-type", "").split(";")[0].lower()
                content_length = int(response.headers.get("content-length", "0") or 0)
                if content_length > max_file_size_bytes():
                    raise HTTPException(status_code=413, detail=f"Video is larger than the {MAX_FILE_SIZE_MB} MB free-mode limit.")
                written = 0
                with destination.open("wb") as output:
                    for chunk in response.iter_bytes(1024 * 1024):
                        written += len(chunk)
                        if written > max_file_size_bytes():
                            raise HTTPException(status_code=413, detail=f"Video is larger than the {MAX_FILE_SIZE_MB} MB free-mode limit.")
                        output.write(chunk)
                if not content_type.startswith("video/") and destination.suffix.lower() not in ALLOWED_EXTENSIONS:
                    destination.unlink(missing_ok=True)
                    raise HTTPException(status_code=400, detail="The URL did not return a direct video file. Upload the video instead.")
    except HTTPException:
        destination.unlink(missing_ok=True)
        raise
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Could not import that direct video URL: {str(exc)[-240:]}")
    metadata = _validate_video(destination)
    db.update_project(
        project_id, original_path=str(destination), source_type="direct_url", source_url=body.url,
        original_filename=Path(parsed.path).name or "imported-video.mp4", status="uploaded", progress=0,
        current_stage="Ready to analyze", error=None, **metadata
    )
    return {"project": _project_response(db.get_project(project_id)), "size_bytes": destination.stat().st_size}


@app.post("/api/projects/{project_id}/analyze")
def analyze_project(project_id: str) -> dict[str, Any]:
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    _validate_rights(project)
    if not project.get("original_path"):
        raise HTTPException(status_code=400, detail="Upload or import a video before analyzing it.")
    if project.get("status") in {"preparing", "transcribing", "detecting_scenes", "detecting_highlights", "scoring_moments", "creating_clips", "adding_captions", "generating_content", "seo_analysis"}:
        return {"project": _project_response(project), "message": "This project is already processing."}
    plan = current_plan()
    if available_daily_jobs(1) <= 0:
        raise HTTPException(status_code=402, detail=f"Daily processing-job limit reached for the {plan['name']} plan. Pro is ₹99/month when billing is configured; no payment was taken.")
    record_usage("processing_jobs", 1, metadata={"project_id": project_id})
    request_limit = int(plan["limits"]["clips_per_project"])
    allowed_clips = available_daily_clips(request_limit)
    if allowed_clips <= 0:
        raise HTTPException(status_code=402, detail=f"Daily clip limit reached for the {plan['name']} plan. Pro is ₹99/month when billing is configured; no payment was taken.")
    db.update_project(project_id, status="preparing", progress=1, current_stage="Queued for local processing", error=None)
    executor.submit(process_project_job, project_id, allowed_clips, owner_id=current_user_id())
    message = "Processing started locally." if allowed_clips >= request_limit else f"Processing started locally with {allowed_clips} remaining clips available today."
    return {"project": _project_response(db.get_project(project_id)), "message": message}


@app.post("/api/projects/{project_id}/retry")
def retry_project(project_id: str) -> dict[str, Any]:
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.get("status") not in {"failed", "finished"}:
        raise HTTPException(status_code=400, detail="This project is already processing or has not been uploaded yet.")
    clear_project_clips(project_id)
    return analyze_project(project_id)


@app.get("/api/projects/{project_id}/clips")
def project_clips(project_id: str) -> list[dict[str, Any]]:
    if not db.get_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return [_clip_response(clip) for clip in db.list_clips(project_id)]  # type: ignore[list-item]


@app.post("/api/projects/{project_id}/logo")
def upload_logo(project_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    suffix = Path(file.filename or "logo.png").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(status_code=400, detail="Logo must be PNG, JPG, JPEG, or WebP.")
    destination = project_root(project_id) / f"logo{suffix}"
    _save_upload(file, destination)
    for clip in db.list_clips(project_id):
        db.update_clip(clip["id"], logo_path=str(destination))
    return {"logo_url": _media_url(str(destination))}


@app.get("/api/library")
def library() -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {"music": [], "sfx": []}
    for kind in ("music", "sfx"):
        directory = STORAGE_ROOT / "library" / kind
        for path in sorted(directory.iterdir() if directory.exists() else []):
            if path.suffix.lower() not in {".mp3", ".wav", ".m4a", ".ogg"}:
                continue
            metadata = {}
            sidecar = path.with_suffix(".json")
            if sidecar.exists():
                try:
                    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
                except Exception:
                    metadata = {}
            result[kind].append({"id": path.name, "name": metadata.get("name", path.stem), "artist": metadata.get("artist", ""), "license": metadata.get("license", "User-provided or local asset"), "url": _media_url(str(path)), "path": str(path)})
    return result


@app.post("/api/library/{kind}/upload")
def upload_library_asset(kind: str, file: UploadFile = File(...), license: str = "User-provided", artist: str = "") -> dict[str, Any]:
    if kind not in {"music", "sfx"}:
        raise HTTPException(status_code=404, detail="Library kind must be music or sfx.")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".mp3", ".wav", ".m4a", ".ogg"}:
        raise HTTPException(status_code=400, detail="Audio must be MP3, WAV, M4A, or OGG.")
    directory = STORAGE_ROOT / "library" / kind
    directory.mkdir(parents=True, exist_ok=True)
    asset_id = f"{uuid.uuid4().hex[:12]}{suffix}"
    destination = directory / asset_id
    try:
        ensure_capacity(int(getattr(file, "size", 0) or 0))
    except RuntimeError as exc:
        raise HTTPException(status_code=507, detail=str(exc))
    size = 0
    with destination.open("wb") as output:
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > 100 * 1024 * 1024:
                destination.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Library audio is limited to 100 MB in Free Mode.")
            output.write(chunk)
    clean_license = (license or "User-provided").strip()[:300]
    destination.with_suffix(".json").write_text(json.dumps({"name": Path(file.filename or asset_id).stem, "artist": artist[:160], "license": clean_license}, indent=2), encoding="utf-8")
    return {"kind": kind, "asset": {"id": asset_id, "name": Path(file.filename or asset_id).stem, "artist": artist[:160], "license": clean_license, "url": _media_url(str(destination)), "path": str(destination)}, "size_bytes": size}


@app.delete("/api/library/{kind}/{asset_id}")
def delete_library_asset(kind: str, asset_id: str) -> dict[str, bool]:
    if kind not in {"music", "sfx"} or Path(asset_id).name != asset_id:
        raise HTTPException(status_code=400, detail="Invalid library asset.")
    path = STORAGE_ROOT / "library" / kind / asset_id
    if not path.exists():
        raise HTTPException(status_code=404, detail="Library asset not found.")
    path.unlink(missing_ok=True)
    path.with_suffix(".json").unlink(missing_ok=True)
    return {"ok": True}


@app.get("/api/clips/{clip_id}")
def get_clip(clip_id: str) -> dict[str, Any]:
    clip = db.get_clip(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    return _clip_response(clip)  # type: ignore[return-value]


@app.get("/api/templates")
def get_templates_endpoint() -> dict[str, Any]:
    return {"templates": list_templates()}


@app.post("/api/clips/{clip_id}/template")
def apply_clip_template(clip_id: str, body: TemplateApplyRequest) -> dict[str, Any]:
    clip = db.get_clip(clip_id)
    template = get_template(body.template_id)
    if not clip or not template:
        raise HTTPException(status_code=404, detail="Clip or template not found")
    if template.get("premium") and not has_entitlement("premium_caption_styles"):
        raise HTTPException(status_code=402, detail="Pro at ₹99/month is required for this template. Basic templates remain free.")
    updated = db.update_clip(clip_id, **template.get("settings", {}))
    return {"clip": _clip_response(updated), "template": template}


@app.get("/api/clips/{clip_id}/content-pack")
def get_clip_content_pack(clip_id: str) -> dict[str, Any]:
    if not db.get_clip(clip_id):
        raise HTTPException(status_code=404, detail="Clip not found")
    if not has_entitlement("full_content_pack"):
        return {"content_pack": None, "premium_required": True, "message": "Full hooks, descriptions, hashtags, keywords, and SEO are available with Pro at ₹99/month when billing is configured."}
    pack = content_db.get_content_pack(clip_id)
    return {"content_pack": pack.get("data") if pack else None, "premium_required": False, "updated_at": pack.get("updated_at") if pack else None}


@app.post("/api/clips/{clip_id}/content-pack/regenerate")
def regenerate_clip_content_pack(clip_id: str, body: ContentPackRegenerateRequest) -> dict[str, Any]:
    clip = db.get_clip(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    if not has_entitlement("full_content_pack"):
        raise HTTPException(status_code=402, detail="Pro at ₹99/month is required for full content packs, hashtags, keywords, and SEO. No payment was taken.")
    try:
        pack = generate_content_pack(clip, language=body.language, tone=body.tone, variant=body.variant)
        saved = content_db.upsert_content_pack(clip_id, pack, language=body.language, tone=body.tone)
        return {"content_pack": saved.get("data"), "updated_at": saved.get("updated_at")}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Local content generation failed: {str(exc)[-400:]}")


@app.post("/api/clips/{clip_id}/thumbnail")
def generate_clip_thumbnail(clip_id: str, body: ThumbnailRequest) -> dict[str, Any]:
    clip = db.get_clip(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    project = db.get_project(clip["project_id"])
    if not project or not project.get("original_path"):
        raise HTTPException(status_code=400, detail="Source video is not available.")
    if body.position not in {"top", "middle", "bottom"}:
        raise HTTPException(status_code=400, detail="Thumbnail text position must be top, middle, or bottom.")
    try:
        from PIL import Image, ImageDraw, ImageFont
        destination = project_root(project["id"]) / "clips" / f"{clip_id}-thumbnail.jpg"
        source_time = min(float(clip["end_sec"]) - 0.1, float(clip["start_sec"]) + body.time_offset)
        make_thumbnail(str(project["original_path"]), destination, max(0, source_time))
        if body.text.strip():
            image = Image.open(destination).convert("RGB")
            draw = ImageDraw.Draw(image, "RGBA")
            try:
                font = ImageFont.truetype("DejaVuSans-Bold.ttf", max(20, image.width // 18))
            except Exception:
                font = ImageFont.load_default()
            text = " ".join(body.text.split())[:120]
            max_width = image.width - 36
            words, lines, current = text.split(), [], ""
            for word in words:
                candidate = f"{current} {word}".strip()
                if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
                    current = candidate
                else:
                    if current: lines.append(current)
                    current = word
            if current: lines.append(current)
            line_height = int(draw.textbbox((0, 0), "Ag", font=font)[3] + 8)
            block_height = len(lines) * line_height + 28
            y = 18 if body.position == "top" else (image.height - block_height) // 2 if body.position == "middle" else image.height - block_height - 18
            draw.rounded_rectangle((12, y, image.width - 12, y + block_height), radius=10, fill=(5, 7, 12, 195))
            for index, line in enumerate(lines):
                bbox = draw.textbbox((0, 0), line, font=font)
                x = (image.width - (bbox[2] - bbox[0])) // 2
                draw.text((x, y + 14 + index * line_height), line, fill=(255, 255, 255, 255), font=font)
            image.save(destination, "JPEG", quality=92)
        updated = db.update_clip(clip_id, thumbnail_path=str(destination))
        return {"clip": _clip_response(updated), "message": "Thumbnail generated from the source video frame."}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Thumbnail generation failed: {str(exc)[-400:]}")


@app.put("/api/clips/{clip_id}")
def update_clip(clip_id: str, body: ClipUpdate) -> dict[str, Any]:
    clip = db.get_clip(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    project = db.get_project(clip["project_id"])
    changes = body.model_dump(exclude_unset=True)
    start = float(changes.get("start_sec", clip["start_sec"]))
    end = float(changes.get("end_sec", clip["end_sec"]))
    duration = float(project.get("duration") or 0) if project else 0
    if start >= end:
        raise HTTPException(status_code=400, detail="End time must be after start time.")
    if duration and end > duration + 0.1:
        raise HTTPException(status_code=400, detail="The clip end time is outside the source video.")
    if "format" in changes and changes["format"] not in {"9:16", "1:1", "16:9", "4:5"}:
        raise HTTPException(status_code=400, detail="Unsupported output format.")
    if changes.get("caption_style") in {"creator", "podcast", "minimal", "high-energy"} and not has_entitlement("premium_caption_styles"):
        raise HTTPException(status_code=402, detail="Pro at ₹99/month is required for premium caption styles. Clean and Bold captions remain free.")
    for asset_key in ("logo_path", "music_path", "sfx_path"):
        asset_value = changes.get(asset_key)
        if asset_value:
            try:
                Path(asset_value).resolve().relative_to(STORAGE_ROOT.resolve())
            except Exception:
                raise HTTPException(status_code=400, detail="Only local project or library assets can be used.")
    changes["duration"] = round(end - start, 3)
    updated = db.update_clip(clip_id, **changes)
    return _clip_response(updated)  # type: ignore[return-value]


@app.post("/api/clips/{clip_id}/render")
def render_clip_endpoint(clip_id: str, body: RenderRequest | None = None) -> dict[str, Any]:
    clip = db.get_clip(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    project = db.get_project(clip["project_id"])
    job = db.create_render_job(project["id"], clip_id)  # type: ignore[index]
    db.update_clip(clip_id, status="rendering", error=None)
    executor.submit(render_clip_job, clip_id, job["id"], owner_id=current_user_id())
    return {"job": job, "clip": _clip_response(db.get_clip(clip_id))}


@app.post("/api/clips/{clip_id}/regenerate")
def regenerate_clip(clip_id: str) -> dict[str, Any]:
    return render_clip_endpoint(clip_id)


@app.get("/api/render-jobs/{job_id}")
def render_job(job_id: str) -> dict[str, Any]:
    job = db.get_render_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Render job not found")
    return job


@app.delete("/api/clips/{clip_id}")
def delete_clip(clip_id: str) -> dict[str, bool]:
    clip = db.get_clip(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    for key in ("video_path", "thumbnail_path"):
        path = clip.get(key)
        if path:
            Path(path).unlink(missing_ok=True)
    db.delete_clip(clip_id)
    return {"ok": True}


@app.get("/api/clips/{clip_id}/download")
def download_clip(clip_id: str) -> FileResponse:
    clip = db.get_clip(clip_id)
    if not clip or not clip.get("video_path") or not Path(clip["video_path"]).exists():
        raise HTTPException(status_code=404, detail="Rendered clip is not ready")
    return FileResponse(clip["video_path"], media_type="video/mp4", filename=f"clipforge-{clip_id[:8]}.mp4")


@app.get("/api/projects/{project_id}/download-all")
def download_all(project_id: str) -> StreamingResponse:
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    clips = [clip for clip in db.list_clips(project_id) if clip.get("video_path") and Path(clip["video_path"]).exists()]
    if not clips:
        raise HTTPException(status_code=404, detail="No rendered clips are ready")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for index, clip in enumerate(clips, 1):
            archive.write(clip["video_path"], arcname=f"{index:02d}-{clip['category'].lower()}-{clip['id'][:8]}.mp4")
    buffer.seek(0)
    headers = {"Content-Disposition": f'attachment; filename="clipforge-{project_id[:8]}-clips.zip"'}
    return StreamingResponse(buffer, media_type="application/zip", headers=headers)
