from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Any

from . import auth_db
from .config import EMAIL_DELIVERY, ENVIRONMENT, FRONTEND_ORIGIN, SMTP_FROM, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USERNAME

logger = logging.getLogger("clipforge.email")


def _send_smtp(recipient: str, subject: str, body: str) -> None:
    if not (SMTP_HOST and SMTP_FROM):
        raise RuntimeError("SMTP is not configured.")
    message = EmailMessage()
    message["From"] = SMTP_FROM
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
        server.starttls()
        if SMTP_USERNAME:
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(message)


def deliver(message: dict[str, Any]) -> dict[str, Any]:
    if EMAIL_DELIVERY == "smtp":
        try:
            _send_smtp(message["recipient"], message["subject"], message["body"])
            return {**message, "status": "sent"}
        except Exception as exc:
            logger.warning("Email delivery failed: %s", str(exc)[-300:])
            return {**message, "status": "failed", "error": "Email delivery is not available."}
    logger.info("Console email [%s] to %s: %s\n%s", message["kind"], message["recipient"], message["subject"], message["body"])
    return {**message, "status": "console"}


def queue_and_deliver(user_id: str | None, recipient: str, kind: str, subject: str, body: str) -> dict[str, Any]:
    message = auth_db.queue_email(user_id, recipient, kind, subject, body)
    message.update({"recipient": recipient, "subject": subject, "body": body})
    return deliver(message)


def verification_url(token: str) -> str:
    return f"{FRONTEND_ORIGIN.rstrip('/')}/verify-email?token={token}"


def password_reset_url(token: str) -> str:
    return f"{FRONTEND_ORIGIN.rstrip('/')}/reset-password?token={token}"


def is_dev_link_allowed() -> bool:
    return ENVIRONMENT != "production" and EMAIL_DELIVERY == "console"
