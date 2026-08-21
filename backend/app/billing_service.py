from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from . import auth_db, billing_db
from .billing import get_provider
from .config import PRO_PRICE_MONTHLY, RAZORPAY_PLAN_ID_PRO, RAZORPAY_USE_SUBSCRIPTIONS
from .email_service import queue_and_deliver
from .plans import PLANS


def _iso_from_unix(value: Any) -> str | None:
    try:
        return datetime.fromtimestamp(int(value), timezone.utc).isoformat() if value else None
    except (TypeError, ValueError, OSError):
        return None


def _user_plan_from_status(status: str, current_end: str | None = None) -> str:
    if status in {"active", "authenticated", "trial", "pending"}:
        if current_end:
            try:
                if datetime.fromisoformat(current_end.replace("Z", "+00:00")) < datetime.now(timezone.utc) and status not in {"pending"}:
                    return "free"
            except ValueError:
                pass
        return "pro"
    return "free"


def _activate_user(user_id: str, plan_id: str) -> None:
    auth_db.update_user(user_id, plan_id=plan_id)


def _notify(user_id: str, kind: str, subject: str, body: str) -> None:
    user = auth_db.get_user(user_id)
    if user:
        queue_and_deliver(user_id, user["email"], kind, subject, body)


def _find_user_for_subscription(provider_subscription_id: str) -> str | None:
    subscription = billing_db.get_subscription_by_provider_id("razorpay", provider_subscription_id)
    if subscription:
        return subscription["user_id"]
    conn = billing_db.db.connect()
    try:
        row = conn.execute("SELECT user_id FROM billing_orders WHERE provider_subscription_id=? ORDER BY created_at DESC LIMIT 1", (provider_subscription_id,)).fetchone()
        return row["user_id"] if row else None
    finally:
        conn.close()


def create_checkout_for_user(user_id: str, plan_id: str = "pro") -> dict[str, Any]:
    plan = PLANS.get(plan_id)
    if not plan or plan_id == "free":
        raise ValueError("Choose the Pro plan to start checkout.")
    provider = get_provider()
    if not provider.configured:
        return {"configured": False, "provider": provider.provider_id, "message": "No payment provider is configured. No payment was taken and Pro was not activated."}
    user = auth_db.get_user(user_id)
    if not user:
        raise ValueError("User account not found.")
    receipt = f"cf_{user_id[:8]}_{int(time.time())}"
    notes = {"clipforge_user_id": user_id, "plan_id": plan_id, "receipt": receipt}
    amount = int(plan.get("price_inr_monthly") or PRO_PRICE_MONTHLY)
    if RAZORPAY_USE_SUBSCRIPTIONS and provider.provider_id == "razorpay" and RAZORPAY_PLAN_ID_PRO:
        subscription_payload = provider.create_subscription(RAZORPAY_PLAN_ID_PRO, notes)
        record = billing_db.create_order(user_id, provider.provider_id, plan_id, amount, receipt, provider_subscription_id=subscription_payload.get("id"), status="pending", payload=subscription_payload)
        billing_db.upsert_subscription(user_id, provider.provider_id, subscription_payload["id"], plan_id, subscription_payload.get("status", "created"), provider_plan_id=RAZORPAY_PLAN_ID_PRO, renewal_at=_iso_from_unix(subscription_payload.get("charge_at")), payload=subscription_payload)
        return {"configured": True, "provider": provider.provider_id, "checkout_type": "subscription", "key_id": getattr(provider, "key_id", None), "subscription_id": subscription_payload.get("id"), "short_url": subscription_payload.get("short_url"), "order": record, "provider_payload": subscription_payload, "message": "Subscription created. Complete the official Razorpay authorisation; Pro activates only after server-side verification."}
    order_payload = provider.create_order(amount, receipt, notes)
    record = billing_db.create_order(user_id, provider.provider_id, plan_id, amount, receipt, provider_order_id=order_payload.get("id"), status="created", payload=order_payload)
    return {"configured": True, "provider": provider.provider_id, "checkout_type": "order", "key_id": getattr(provider, "key_id", None) or None, "order": record, "provider_payload": order_payload, "message": "Order created. Complete payment with the official gateway; Pro activates only after server-side verification."}


def verify_checkout_for_user(user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    provider = get_provider()
    if not provider.configured:
        raise RuntimeError("No payment provider is configured.")
    order_id = str(payload.get("razorpay_order_id") or payload.get("order_id") or "")
    payment_id = str(payload.get("razorpay_payment_id") or payload.get("payment_id") or "")
    subscription_id = str(payload.get("razorpay_subscription_id") or payload.get("subscription_id") or "")
    signature = str(payload.get("razorpay_signature") or payload.get("signature") or "")
    if not payment_id or not signature:
        raise ValueError("Payment verification fields are incomplete.")
    if subscription_id:
        record = billing_db.get_subscription_by_provider_id(provider.provider_id, subscription_id)
        if not record or record["user_id"] != user_id:
            raise ValueError("Subscription does not belong to this account.")
        if not provider.verify_subscription_payment(subscription_id, payment_id, signature):
            raise ValueError("Payment signature verification failed.")
        billing_db.create_payment(user_id, provider.provider_id, payment_id, int(record["plan_id"] == "pro") * PRO_PRICE_MONTHLY, "captured", subscription_id=subscription_id, payload=payload)
        updated = billing_db.upsert_subscription(user_id, provider.provider_id, subscription_id, record["plan_id"], "active", provider_plan_id=record.get("provider_plan_id"), current_start=datetime.now(timezone.utc).isoformat(), current_end=(datetime.now(timezone.utc) + timedelta(days=30)).isoformat(), renewal_at=(datetime.now(timezone.utc) + timedelta(days=30)).isoformat(), payload=payload)
        _activate_user(user_id, "pro")
        invoice = billing_db.create_invoice(user_id, "pro", PRO_PRICE_MONTHLY, subscription_id=updated["id"], provider=provider.provider_id, payment_method="subscription", payload=payload)
        _notify(user_id, "payment_success", "ClipForge Pro is active", "Your Razorpay subscription payment was verified server-side. Pro features are now active.")
        return {"verified": True, "status": "active", "subscription": updated, "invoice": invoice, "message": "Payment verified server-side and Pro is active."}
    order = billing_db.get_order_by_provider_id(provider.provider_id, order_id)
    if not order or order["user_id"] != user_id:
        raise ValueError("Order does not belong to this account.")
    if not provider.verify_payment(order_id, payment_id, signature):
        raise ValueError("Payment signature verification failed.")
    payment = provider.fetch_payment(payment_id)
    if str(payment.get("status", "")).lower() != "captured":
        raise ValueError("Payment is not captured by the provider. Pro was not activated.")
    stored_payment = billing_db.create_payment(user_id, provider.provider_id, payment_id, int(order["amount"]), "captured", order_id=order["id"], currency=order["currency"], method=payment.get("method"), payload=payment)
    billing_db.update_order(order["id"], status="paid", provider_payload=payment)
    start = datetime.now(timezone.utc)
    end = start + timedelta(days=30)
    subscription = billing_db.upsert_subscription(user_id, provider.provider_id, f"order:{order['provider_order_id']}", order["plan_id"], "active", current_start=start.isoformat(), current_end=end.isoformat(), renewal_at=end.isoformat(), payload=payment)
    _activate_user(user_id, order["plan_id"])
    invoice = billing_db.create_invoice(user_id, order["plan_id"], int(order["amount"]), subscription_id=subscription["id"], payment_id=stored_payment["id"], provider=provider.provider_id, payment_method=payment.get("method"), payload=payment)
    _notify(user_id, "payment_success", "ClipForge Pro is active", "Your payment was verified server-side. Pro features are now active for the recorded billing period.")
    return {"verified": True, "status": "active", "payment": stored_payment, "subscription": subscription, "invoice": invoice, "message": "Payment verified server-side and Pro is active."}


def _entity(payload: dict[str, Any], key: str) -> dict[str, Any]:
    return (((payload.get("payload") or {}).get(key) or {}).get("entity") or {})


def handle_webhook(provider_id: str, raw_body: bytes, signature: str, event_id: str | None) -> dict[str, Any]:
    provider = get_provider(provider_id)
    if not provider.configured:
        raise RuntimeError("The selected payment provider is not configured.")
    if not provider.verify_webhook(raw_body, signature):
        raise ValueError("Webhook signature verification failed.")
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Webhook payload is invalid JSON.") from exc
    event_type = str(payload.get("event") or "unknown")
    event_key = event_id or hashlib.sha256(raw_body).hexdigest()
    event, is_new = billing_db.record_event(provider_id, event_key, event_type, payload)
    if not is_new:
        return {"ok": True, "duplicate": True, "event_id": event_key}
    try:
        if event_type in {"payment.captured", "order.paid"}:
            payment = _entity(payload, "payment")
            order_id = payment.get("order_id")
            order = billing_db.get_order_by_provider_id(provider_id, order_id) if order_id else None
            if order:
                user_id = order["user_id"]
                stored = billing_db.create_payment(user_id, provider_id, payment.get("id", ""), int(order["amount"]), "captured", order_id=order["id"], method=payment.get("method"), payload=payment)
                billing_db.update_order(order["id"], status="paid", provider_payload=payload)
                start = datetime.now(timezone.utc); end = start + timedelta(days=30)
                subscription = billing_db.upsert_subscription(user_id, provider_id, f"order:{order['provider_order_id']}", order["plan_id"], "active", current_start=start.isoformat(), current_end=end.isoformat(), renewal_at=end.isoformat(), payload=payload)
                _activate_user(user_id, order["plan_id"])
                billing_db.create_invoice(user_id, order["plan_id"], int(order["amount"]), subscription_id=subscription["id"], payment_id=stored["id"], provider=provider_id, payment_method=payment.get("method"), payload=payload)
                _notify(user_id, "payment_success", "ClipForge Pro payment received", "Your provider payment webhook was verified and Pro access is active.")
        elif event_type == "payment.failed":
            payment = _entity(payload, "payment")
            order = billing_db.get_order_by_provider_id(provider_id, payment.get("order_id", "")) if payment.get("order_id") else None
            if order:
                billing_db.update_order(order["id"], status="failed", provider_payload=payload)
                _notify(order["user_id"], "payment_failed", "ClipForge payment failed", "The payment provider reported a failed payment. No Pro entitlement was activated.")
        elif event_type.startswith("subscription."):
            subscription_entity = _entity(payload, "subscription")
            provider_subscription_id = subscription_entity.get("id")
            if provider_subscription_id:
                user_id = _find_user_for_subscription(provider_subscription_id)
                existing = billing_db.get_subscription_by_provider_id(provider_id, provider_subscription_id)
                if user_id and existing:
                    status_map = {"subscription.activated": "active", "subscription.authenticated": "active", "subscription.charged": "active", "subscription.pending": "pending", "subscription.paused": "paused", "subscription.resumed": "active", "subscription.cancelled": "cancelled", "subscription.completed": "expired", "subscription.expired": "expired", "subscription.halted": "failed"}
                    status = status_map.get(event_type, existing["status"])
                    updated = billing_db.upsert_subscription(user_id, provider_id, provider_subscription_id, existing["plan_id"], status, provider_plan_id=existing.get("provider_plan_id"), current_start=_iso_from_unix(subscription_entity.get("current_start")), current_end=_iso_from_unix(subscription_entity.get("current_end")), renewal_at=_iso_from_unix(subscription_entity.get("charge_at")), cancelled_at=_iso_from_unix(subscription_entity.get("ended_at")) if status in {"cancelled", "expired"} else None, payload=payload)
                    active_plan = _user_plan_from_status(status, updated.get("current_end"))
                    _activate_user(user_id, active_plan)
                    if event_type == "subscription.charged":
                        payment_entity = _entity(payload, "payment")
                        payment_id = payment_entity.get("id")
                        if payment_id:
                            payment = billing_db.create_payment(user_id, provider_id, payment_id, PRO_PRICE_MONTHLY, "captured", subscription_id=updated["id"], method=payment_entity.get("method"), payload=payload)
                            billing_db.create_invoice(user_id, existing["plan_id"], PRO_PRICE_MONTHLY, subscription_id=updated["id"], payment_id=payment["id"], provider=provider_id, payment_method=payment_entity.get("method"), payload=payload)
                            _notify(user_id, "subscription_renewed", "ClipForge Pro renewed", "Your recurring provider payment was verified and your Pro access continues.")
        billing_db.mark_event(event["id"], "processed")
        return {"ok": True, "event_id": event_key, "event_type": event_type}
    except Exception as exc:
        billing_db.mark_event(event["id"], "failed", str(exc)[-500:])
        raise


def cancel_for_user(user_id: str, subscription_id: str, cancel_at_cycle_end: bool = True) -> dict[str, Any]:
    provider = get_provider()
    subscription = billing_db.get_subscription_by_provider_id(provider.provider_id, subscription_id)
    if not subscription or subscription["user_id"] != user_id:
        raise ValueError("Subscription was not found for this account.")
    result = provider.cancel_subscription(subscription_id, cancel_at_cycle_end)
    updated = billing_db.upsert_subscription(user_id, provider.provider_id, subscription_id, subscription["plan_id"], "cancelled" if not cancel_at_cycle_end else "active", provider_plan_id=subscription.get("provider_plan_id"), current_start=subscription.get("current_start"), current_end=subscription.get("current_end"), renewal_at=subscription.get("renewal_at"), cancelled_at=datetime.now(timezone.utc).isoformat() if not cancel_at_cycle_end else None, payload=result)
    if not cancel_at_cycle_end:
        _activate_user(user_id, "free")
    return {"subscription": updated, "provider": result, "message": "Cancellation request sent to the official provider. Access remains until the recorded renewal date when cancelling at cycle end." if cancel_at_cycle_end else "Subscription cancelled; Pro access was removed."}


def pause_for_user(user_id: str) -> dict[str, Any]:
    provider = get_provider()
    subscription = billing_db.get_current_subscription(user_id)
    if not subscription or subscription["provider" ] != provider.provider_id:
        raise ValueError("No provider subscription is available to pause.")
    result = provider.pause_subscription(subscription["provider_subscription_id"])
    updated = billing_db.upsert_subscription(user_id, provider.provider_id, subscription["provider_subscription_id"], subscription["plan_id"], "paused", provider_plan_id=subscription.get("provider_plan_id"), current_start=subscription.get("current_start"), current_end=subscription.get("current_end"), renewal_at=subscription.get("renewal_at"), paused_at=datetime.now(timezone.utc).isoformat(), payload=result)
    _activate_user(user_id, "free")
    return {"subscription": updated, "provider": result, "message": "Subscription paused with the official provider."}


def resume_for_user(user_id: str) -> dict[str, Any]:
    provider = get_provider()
    subscription = billing_db.get_current_subscription(user_id)
    if not subscription or subscription["provider"] != provider.provider_id:
        raise ValueError("No provider subscription is available to resume.")
    result = provider.resume_subscription(subscription["provider_subscription_id"])
    updated = billing_db.upsert_subscription(user_id, provider.provider_id, subscription["provider_subscription_id"], subscription["plan_id"], "active", provider_plan_id=subscription.get("provider_plan_id"), current_start=subscription.get("current_start"), current_end=subscription.get("current_end"), renewal_at=subscription.get("renewal_at"), paused_at=None, payload=result)
    _activate_user(user_id, "pro")
    return {"subscription": updated, "provider": result, "message": "Subscription resumed with the official provider."}
