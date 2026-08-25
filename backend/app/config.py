from __future__ import annotations

import os
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
STORAGE_ROOT = Path(os.getenv("STORAGE_ROOT", str(BACKEND_ROOT / "storage")))
DB_PATH = Path(os.getenv("DATABASE_PATH", str(STORAGE_ROOT / "viral_clips.sqlite3")))

MAX_VIDEO_DURATION = int(os.getenv("MAX_VIDEO_DURATION", "1800"))
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "1000"))
MAX_CLIPS = int(os.getenv("MAX_CLIPS", os.getenv("FREE_PLAN_CLIPS", "10")))
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "tiny.en")
PROCESSING_WORKERS = int(os.getenv("PROCESSING_WORKERS", "2"))
MAX_STORAGE_GB = float(os.getenv("MAX_STORAGE_GB", "20"))
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "0"))
FREE_MODE_DEFAULT = os.getenv("FREE_MODE", "true").lower() not in {"0", "false", "off", "no"}
LOCAL_AI = os.getenv("LOCAL_AI", "true").lower() in {"1", "true", "on", "yes"}
ALLOW_CLOUD_AI = os.getenv("ALLOW_CLOUD_AI", "false").lower() in {"1", "true", "on", "yes"}
LOCAL_MODEL = os.getenv("LOCAL_MODEL", os.getenv("WHISPER_MODEL", "tiny.en"))
PRIVACY_MODE_DEFAULT = os.getenv("PRIVACY_MODE", "true").lower() not in {"0", "false", "off", "no"}
ALLOW_OFFICIAL_APIS = os.getenv("ALLOW_OFFICIAL_APIS", "false").lower() in {"1", "true", "on", "yes"}
AUTH_REQUIRED = os.getenv("AUTH_REQUIRED", "true").lower() in {"1", "true", "on", "yes"}
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "lax").lower()
if SESSION_COOKIE_SAMESITE not in {"lax", "strict", "none"}:
    SESSION_COOKIE_SAMESITE = "lax"
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://127.0.0.1:5173")
PUBLIC_API_URL = os.getenv("PUBLIC_API_URL", "")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
EMAIL_DELIVERY = os.getenv("EMAIL_DELIVERY", "console")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USERNAME)
PAYMENT_PROVIDER = os.getenv("PAYMENT_PROVIDER", "none").lower()
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPSESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "clipforge_session")
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "lax").strip().lower()
if SESSION_COOKIE_SAMESITE not in {"lax", "strict", "none"}:
    SESSION_COOKIE_SAMESITE = "lax"
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://127.0.0.1:5173")
PUBLIC_API_URL = os.getenv("PUBLIC_API_URL", "")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
EMAIL_DELIVERY = os.getenv("EMAIL_DELIVERY", "console")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USERNAME)AY_WEBHOOK_SECRET", "")
RAZORPAY_PLAN_ID_PRO = os.getenv("RAZORPAY_PLAN_ID_PRO", "")
RAZORPAY_USE_SUBSCRIPTIONS = os.getenv("RAZORPAY_USE_SUBSCRIPTIONS", "false").lower() in {"1", "true", "on", "yes"}
PRO_PRICE_MONTHLY = int(os.getenv("PRO_PRICE_MONTHLY", "99"))
FREE_PLAN_CLIPS = int(os.getenv("FREE_PLAN_CLIPS", str(MAX_CLIPS)))
FREE_PLAN_VIDEOS = int(os.getenv("FREE_PLAN_VIDEOS", "2"))
MAX_PASSWORD_RESET_HOURS = int(os.getenv("MAX_PASSWORD_RESET_HOURS", "2"))
TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "0"))
ADMIN_EMAILS = {item.strip().lower() for item in os.getenv("ADMIN_EMAILS", "").split(",") if item.strip()}

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
BLOCKED_URL_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "youtu.be",
    "tiktok.com",
    "www.tiktok.com",
    "instagram.com",
    "www.instagram.com",
    "facebook.com",
    "www.facebook.com",
    "x.com",
    "twitter.com",
}


def ensure_storage() -> None:
    STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    (STORAGE_ROOT / "projects").mkdir(parents=True, exist_ok=True)
    (STORAGE_ROOT / "library" / "music").mkdir(parents=True, exist_ok=True)
    (STORAGE_ROOT / "library" / "sfx").mkdir(parents=True, exist_ok=True)
    (STORAGE_ROOT / "library" / "logos").mkdir(parents=True, exist_ok=True)


def project_root(project_id: str) -> Path:
    path = STORAGE_ROOT / "projects" / project_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def max_file_size_bytes() -> int:
    return MAX_FILE_SIZE_MB * 1024 * 1024
