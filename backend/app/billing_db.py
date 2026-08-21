from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Any

from . import db


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def init_billing_db() -> None:
    conn = db.connect()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS billing_customers (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL UNIQUE,
                provider TEXT NOT NULL,
                provider_customer_id TEXT NOT NULL,
                email TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS billing_orders (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                provider_order_id TEXT,
                provider_subscription_id TEXT,
                plan_id TEXT NOT NULL,
                amount INTEGER NOT NULL,
                currency TEXT NOT NULL DEFAULT 'INR',
                status TEXT NOT NULL DEFAULT 'created',
                receipt TEXT NOT NULL,
                provider_payload TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS billing_payments (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                order_id TEXT,
                subscription_id TEXT,
                provider TEXT NOT NULL,
                provider_payment_id TEXT NOT NULL UNIQUE,
                amount INTEGER NOT NULL,
                currency TEXT NOT NULL DEFAULT 'INR',
                status TEXT NOT NULL DEFAULT 'pending',
                method TEXT,
                provider_payload TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS billing_subscriptions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                provider_subscription_id TEXT NOT NULL UNIQUE,
                provider_plan_id TEXT,
                plan_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                current_start TEXT,
                current_end TEXT,
                renewal_at TEXT,
                cancelled_at TEXT,
                paused_at TEXT,
                quantity INTEGER NOT NULL DEFAULT 1,
                provider_payload TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS billing_invoices (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                subscription_id TEXT,
                payment_id TEXT,
                provider TEXT NOT NULL,
                provider_invoice_id TEXT,
                invoice_number TEXT NOT NULL UNIQUE,
                plan_id TEXT NOT NULL,
                amount INTEGER NOT NULL,
                tax INTEGER NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'INR',
                status TEXT NOT NULL DEFAULT 'paid',
                payment_method TEXT,
                invoice_date TEXT NOT NULL,
                pdf_url TEXT,
                provider_payload TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS billing_events (
                id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                provider_event_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'received',
                error TEXT,
                created_at TEXT NOT NULL,
                processed_at TEXT,
                UNIQUE(provider, provider_event_id)
            );
            CREATE INDEX IF NOT EXISTS idx_billing_orders_user ON billing_orders(user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_billing_payments_user ON billing_payments(user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_billing_invoices_user ON billing_invoices(user_id, invoice_date DESC);
            CREATE INDEX IF NOT EXISTS idx_billing_subscriptions_user ON billing_subscriptions(user_id, updated_at DESC);
            """
        )
        conn.commit()
    finally:
        conn.close()


def get_customer(user_id: str) -> dict[str, Any] | None:
    conn = db.connect()
    try:
        return _row(conn.execute("SELECT * FROM billing_customers WHERE user_id=?", (user_id,)).fetchone())
    finally:
        conn.close()


def upsert_customer(user_id: str, provider: str, provider_customer_id: str, email: str = "", name: str = "") -> dict[str, Any]:
    now = now_iso()
    existing = get_customer(user_id)
    conn = db.connect()
    try:
        if existing:
            conn.execute("UPDATE billing_customers SET provider=?,provider_customer_id=?,email=?,name=?,updated_at=? WHERE user_id=?", (provider, provider_customer_id, email, name, now, user_id))
        else:
            conn.execute("INSERT INTO billing_customers(id,user_id,provider,provider_customer_id,email,name,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (secrets.token_urlsafe(15), user_id, provider, provider_customer_id, email, name, now, now))
        conn.commit()
    finally:
        conn.close()
    return get_customer(user_id)  # type: ignore[return-value]


def create_order(user_id: str, provider: str, plan_id: str, amount: int, receipt: str, provider_order_id: str | None = None, provider_subscription_id: str | None = None, status: str = "created", payload: dict[str, Any] | None = None) -> dict[str, Any]:
    order_id = secrets.token_urlsafe(15)
    now = now_iso()
    conn = db.connect()
    try:
        conn.execute("INSERT INTO billing_orders(id,user_id,provider,provider_order_id,provider_subscription_id,plan_id,amount,receipt,status,provider_payload,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (order_id, user_id, provider, provider_order_id, provider_subscription_id, plan_id, amount, receipt, status, json.dumps(payload or {}), now, now))
        conn.commit()
    finally:
        conn.close()
    return get_order(order_id)  # type: ignore[return-value]


def get_order(order_id: str) -> dict[str, Any] | None:
    conn = db.connect()
    try:
        return _row(conn.execute("SELECT * FROM billing_orders WHERE id=?", (order_id,)).fetchone())
    finally:
        conn.close()


def get_order_for_user(order_id: str, user_id: str) -> dict[str, Any] | None:
    conn = db.connect()
    try:
        return _row(conn.execute("SELECT * FROM billing_orders WHERE id=? AND user_id=?", (order_id, user_id)).fetchone())
    finally:
        conn.close()


def get_order_by_provider_id(provider: str, provider_order_id: str) -> dict[str, Any] | None:
    conn = db.connect()
    try:
        return _row(conn.execute("SELECT * FROM billing_orders WHERE provider=? AND provider_order_id=?", (provider, provider_order_id)).fetchone())
    finally:
        conn.close()


def update_order(order_id: str, **fields: Any) -> dict[str, Any] | None:
    allowed = {"provider_order_id", "provider_subscription_id", "status", "provider_payload"}
    data = {key: (json.dumps(value) if key == "provider_payload" and not isinstance(value, str) else value) for key, value in fields.items() if key in allowed}
    data["updated_at"] = now_iso()
    conn = db.connect()
    try:
        conn.execute(f"UPDATE billing_orders SET {', '.join(f'{key}=?' for key in data)} WHERE id=?", [*data.values(), order_id])
        conn.commit()
    finally:
        conn.close()
    return get_order(order_id)


def create_payment(user_id: str, provider: str, provider_payment_id: str, amount: int, status: str, order_id: str | None = None, subscription_id: str | None = None, currency: str = "INR", method: str | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payment_id = secrets.token_urlsafe(15)
    now = now_iso()
    conn = db.connect()
    try:
        conn.execute("INSERT OR IGNORE INTO billing_payments(id,user_id,order_id,subscription_id,provider,provider_payment_id,amount,currency,status,method,provider_payload,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (payment_id, user_id, order_id, subscription_id, provider, provider_payment_id, amount, currency, status, method, json.dumps(payload or {}), now, now))
        conn.commit()
    finally:
        conn.close()
    return get_payment_by_provider_id(provider, provider_payment_id)  # type: ignore[return-value]


def get_payment(payment_id: str) -> dict[str, Any] | None:
    conn = db.connect()
    try:
        return _row(conn.execute("SELECT * FROM billing_payments WHERE id=?", (payment_id,)).fetchone())
    finally:
        conn.close()


def update_payment(payment_id: str, **fields: Any) -> dict[str, Any] | None:
    allowed = {"status", "provider_payload", "method"}
    data = {key: (json.dumps(value) if key == "provider_payload" and not isinstance(value, str) else value) for key, value in fields.items() if key in allowed}
    data["updated_at"] = now_iso()
    conn = db.connect()
    try:
        conn.execute(f"UPDATE billing_payments SET {', '.join(f'{key}=?' for key in data)} WHERE id=?", [*data.values(), payment_id])
        conn.commit()
    finally:
        conn.close()
    return get_payment(payment_id)


def get_payment_by_provider_id(provider: str, provider_payment_id: str) -> dict[str, Any] | None:
    conn = db.connect()
    try:
        return _row(conn.execute("SELECT * FROM billing_payments WHERE provider=? AND provider_payment_id=?", (provider, provider_payment_id)).fetchone())
    finally:
        conn.close()


def list_payments(user_id: str) -> list[dict[str, Any]]:
    conn = db.connect()
    try:
        return [dict(row) for row in conn.execute("SELECT * FROM billing_payments WHERE user_id=? ORDER BY created_at DESC", (user_id,)).fetchall()]
    finally:
        conn.close()


def upsert_subscription(user_id: str, provider: str, provider_subscription_id: str, plan_id: str, status: str, provider_plan_id: str | None = None, current_start: str | None = None, current_end: str | None = None, renewal_at: str | None = None, cancelled_at: str | None = None, paused_at: str | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    now = now_iso()
    existing = get_subscription_by_provider_id(provider, provider_subscription_id)
    conn = db.connect()
    try:
        if existing:
            conn.execute("UPDATE billing_subscriptions SET user_id=?,provider_plan_id=?,plan_id=?,status=?,current_start=?,current_end=?,renewal_at=?,cancelled_at=?,paused_at=?,provider_payload=?,updated_at=? WHERE provider=? AND provider_subscription_id=?", (user_id, provider_plan_id, plan_id, status, current_start, current_end, renewal_at, cancelled_at, paused_at, json.dumps(payload or {}), now, provider, provider_subscription_id))
        else:
            conn.execute("INSERT INTO billing_subscriptions(id,user_id,provider,provider_subscription_id,provider_plan_id,plan_id,status,current_start,current_end,renewal_at,cancelled_at,paused_at,provider_payload,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (secrets.token_urlsafe(15), user_id, provider, provider_subscription_id, provider_plan_id, plan_id, status, current_start, current_end, renewal_at, cancelled_at, paused_at, json.dumps(payload or {}), now, now))
        conn.commit()
    finally:
        conn.close()
    return get_subscription_by_provider_id(provider, provider_subscription_id)  # type: ignore[return-value]


def get_subscription_by_provider_id(provider: str, provider_subscription_id: str) -> dict[str, Any] | None:
    conn = db.connect()
    try:
        return _row(conn.execute("SELECT * FROM billing_subscriptions WHERE provider=? AND provider_subscription_id=?", (provider, provider_subscription_id)).fetchone())
    finally:
        conn.close()


def get_current_subscription(user_id: str) -> dict[str, Any] | None:
    conn = db.connect()
    try:
        return _row(conn.execute("SELECT * FROM billing_subscriptions WHERE user_id=? ORDER BY updated_at DESC LIMIT 1", (user_id,)).fetchone())
    finally:
        conn.close()


def list_subscriptions(user_id: str) -> list[dict[str, Any]]:
    conn = db.connect()
    try:
        return [dict(row) for row in conn.execute("SELECT * FROM billing_subscriptions WHERE user_id=? ORDER BY updated_at DESC", (user_id,)).fetchall()]
    finally:
        conn.close()


def create_invoice(user_id: str, plan_id: str, amount: int, status: str = "paid", subscription_id: str | None = None, payment_id: str | None = None, provider: str = "razorpay", provider_invoice_id: str | None = None, payment_method: str | None = None, tax: int = 0, pdf_url: str | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if payment_id:
        conn = db.connect()
        try:
            existing = conn.execute("SELECT * FROM billing_invoices WHERE payment_id=?", (payment_id,)).fetchone()
            if existing:
                return dict(existing)
        finally:
            conn.close()
    invoice_id = secrets.token_urlsafe(15)
    invoice_number = f"CF-{datetime.now(timezone.utc).strftime('%Y%m')}-{secrets.token_hex(4).upper()}"
    now = now_iso()
    conn = db.connect()
    try:
        conn.execute("INSERT INTO billing_invoices(id,user_id,subscription_id,payment_id,provider,provider_invoice_id,invoice_number,plan_id,amount,tax,currency,status,payment_method,invoice_date,pdf_url,provider_payload,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (invoice_id, user_id, subscription_id, payment_id, provider, provider_invoice_id, invoice_number, plan_id, amount, tax, "INR", status, payment_method, now, pdf_url, json.dumps(payload or {}), now))
        conn.commit()
    finally:
        conn.close()
    return get_invoice(invoice_id)  # type: ignore[return-value]


def get_invoice(invoice_id: str) -> dict[str, Any] | None:
    conn = db.connect()
    try:
        return _row(conn.execute("SELECT * FROM billing_invoices WHERE id=?", (invoice_id,)).fetchone())
    finally:
        conn.close()


def list_invoices(user_id: str) -> list[dict[str, Any]]:
    conn = db.connect()
    try:
        return [dict(row) for row in conn.execute("SELECT * FROM billing_invoices WHERE user_id=? ORDER BY invoice_date DESC", (user_id,)).fetchall()]
    finally:
        conn.close()


def record_event(provider: str, provider_event_id: str, event_type: str, payload: dict[str, Any]) -> tuple[dict[str, Any] | None, bool]:
    event_id = secrets.token_urlsafe(15)
    now = now_iso()
    conn = db.connect()
    try:
        try:
            conn.execute("INSERT INTO billing_events(id,provider,provider_event_id,event_type,payload,created_at) VALUES(?,?,?,?,?,?)", (event_id, provider, provider_event_id, event_type, json.dumps(payload), now))
            conn.commit()
            return {"id": event_id, "provider": provider, "provider_event_id": provider_event_id, "event_type": event_type, "payload": payload, "status": "received"}, True
        except sqlite3.IntegrityError:
            row = conn.execute("SELECT * FROM billing_events WHERE provider=? AND provider_event_id=?", (provider, provider_event_id)).fetchone()
            return _row(row), False
    finally:
        conn.close()


def mark_event(event_id: str, status: str, error: str | None = None) -> None:
    conn = db.connect()
    try:
        conn.execute("UPDATE billing_events SET status=?,error=?,processed_at=? WHERE id=?", (status, error, now_iso(), event_id))
        conn.commit()
    finally:
        conn.close()


def list_events(limit: int = 100) -> list[dict[str, Any]]:
    conn = db.connect()
    try:
        return [dict(row) for row in conn.execute("SELECT * FROM billing_events ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()]
    finally:
        conn.close()


def active_plan_for_user(user_id: str) -> str | None:
    subscription = get_current_subscription(user_id)
    if not subscription:
        return None
    status = str(subscription.get("status") or "")
    if status not in {"active", "authenticated", "trial", "pending"}:
        return "free"
    current_end = subscription.get("current_end") or subscription.get("renewal_at")
    if current_end:
        try:
            if datetime.fromisoformat(str(current_end).replace("Z", "+00:00")) < datetime.now(timezone.utc) and status != "pending":
                return "free"
        except ValueError:
            pass
    return str(subscription.get("plan_id") or "free")
