from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from abc import ABC, abstractmethod
from typing import Any

import httpx

from .config import (
    PAYMENT_PROVIDER,
    RAZORPAY_KEY_ID,
    RAZORPAY_KEY_SECRET,
    RAZORPAY_PLAN_ID_PRO,
    RAZORPAY_USE_SUBSCRIPTIONS,
    RAZORPAY_WEBHOOK_SECRET,
)


class PaymentProvider(ABC):
    provider_id = "none"
    supports_subscriptions = False

    @property
    @abstractmethod
    def configured(self) -> bool:
        raise NotImplementedError

    def status(self) -> dict[str, Any]:
        return {"provider": self.provider_id, "configured": self.configured, "supports_subscriptions": self.supports_subscriptions}

    def create_customer(self, name: str, email: str) -> dict[str, Any]:
        raise RuntimeError(f"{self.provider_id} customer creation is not configured.")

    def create_order(self, amount_inr: int, receipt: str, notes: dict[str, str]) -> dict[str, Any]:
        raise RuntimeError(f"{self.provider_id} order creation is not configured.")

    def create_subscription(self, provider_plan_id: str, notes: dict[str, str]) -> dict[str, Any]:
        raise RuntimeError(f"{self.provider_id} subscriptions are not configured.")

    def fetch_payment(self, payment_id: str) -> dict[str, Any]:
        raise RuntimeError(f"{self.provider_id} payment lookup is not configured.")

    def verify_payment(self, order_id: str, payment_id: str, signature: str) -> bool:
        raise RuntimeError(f"{self.provider_id} payment verification is not configured.")

    def verify_subscription_payment(self, subscription_id: str, payment_id: str, signature: str) -> bool:
        raise RuntimeError(f"{self.provider_id} subscription verification is not configured.")

    def verify_webhook(self, raw_body: bytes, signature: str) -> bool:
        raise RuntimeError(f"{self.provider_id} webhook verification is not configured.")

    def refund(self, payment_id: str, amount_inr: int | None = None, notes: dict[str, str] | None = None) -> dict[str, Any]:
        raise RuntimeError(f"{self.provider_id} refunds are not configured.")

    def cancel_subscription(self, subscription_id: str, cancel_at_cycle_end: bool = True) -> dict[str, Any]:
        raise RuntimeError(f"{self.provider_id} subscription cancellation is not configured.")

    def pause_subscription(self, subscription_id: str) -> dict[str, Any]:
        raise RuntimeError(f"{self.provider_id} subscription pause is not configured.")

    def resume_subscription(self, subscription_id: str) -> dict[str, Any]:
        raise RuntimeError(f"{self.provider_id} subscription resume is not configured.")


class UnconfiguredProvider(PaymentProvider):
    def __init__(self, provider_id: str):
        self.provider_id = provider_id

    @property
    def configured(self) -> bool:
        return False


class RazorpayProvider(PaymentProvider):
    provider_id = "razorpay"
    supports_subscriptions = True
    base_url = "https://api.razorpay.com/v1"

    @property
    def key_id(self) -> str:
        return RAZORPAY_KEY_ID

    @property
    def configured(self) -> bool:
        return bool(RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET)

    def status(self) -> dict[str, Any]:
        return {**super().status(), "subscription_plan_configured": bool(RAZORPAY_PLAN_ID_PRO), "webhook_configured": bool(RAZORPAY_WEBHOOK_SECRET), "mode": "live" if RAZORPAY_KEY_ID.startswith("rzp_live_") else "test" if RAZORPAY_KEY_ID else "unconfigured"}

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError("Razorpay is not configured. Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET on the server.")
        try:
            with httpx.Client(base_url=self.base_url, auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET), timeout=30) as client:
                response = client.request(method, path, **kwargs)
            if response.status_code >= 400:
                detail = "Razorpay rejected the request."
                try:
                    error = response.json().get("error", {})
                    detail = str(error.get("description") or error.get("code") or detail)
                except Exception:
                    pass
                raise RuntimeError(detail[:300])
            return response.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Razorpay request failed: {str(exc)[:240]}") from exc

    def create_customer(self, name: str, email: str) -> dict[str, Any]:
        return self._request("POST", "/customers", json={"name": name[:120], "email": email[:160]})

    def create_order(self, amount_inr: int, receipt: str, notes: dict[str, str]) -> dict[str, Any]:
        return self._request("POST", "/orders", json={"amount": int(amount_inr * 100), "currency": "INR", "receipt": receipt[:40], "notes": notes})

    def create_subscription(self, provider_plan_id: str, notes: dict[str, str]) -> dict[str, Any]:
        return self._request("POST", "/subscriptions", json={"plan_id": provider_plan_id, "total_count": 120, "quantity": 1, "customer_notify": True, "notes": notes})

    def fetch_payment(self, payment_id: str) -> dict[str, Any]:
        return self._request("GET", f"/payments/{payment_id}")

    def verify_payment(self, order_id: str, payment_id: str, signature: str) -> bool:
        expected = hmac.new(RAZORPAY_KEY_SECRET.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def verify_subscription_payment(self, subscription_id: str, payment_id: str, signature: str) -> bool:
        expected = hmac.new(RAZORPAY_KEY_SECRET.encode(), f"{payment_id}|{subscription_id}".encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def verify_webhook(self, raw_body: bytes, signature: str) -> bool:
        if not RAZORPAY_WEBHOOK_SECRET:
            return False
        expected = hmac.new(RAZORPAY_WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def refund(self, payment_id: str, amount_inr: int | None = None, notes: dict[str, str] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if amount_inr is not None:
            payload["amount"] = int(amount_inr * 100)
        if notes:
            payload["notes"] = notes
        return self._request("POST", f"/payments/{payment_id}/refund", json=payload)

    def cancel_subscription(self, subscription_id: str, cancel_at_cycle_end: bool = True) -> dict[str, Any]:
        return self._request("POST", f"/subscriptions/{subscription_id}/cancel", json={"cancel_at_cycle_end": cancel_at_cycle_end})

    def pause_subscription(self, subscription_id: str) -> dict[str, Any]:
        return self._request("POST", f"/subscriptions/{subscription_id}/pause", json={"pause_at": "now"})

    def resume_subscription(self, subscription_id: str) -> dict[str, Any]:
        return self._request("POST", f"/subscriptions/{subscription_id}/resume", json={"resume_at": "now"})


_PROVIDER_TYPES = {"cashfree", "phonepe", "stripe", "paypal", "paddle", "lemonsqueezy", "lemon_squeezy"}


def get_provider(provider_id: str | None = None) -> PaymentProvider:
    selected = (provider_id or PAYMENT_PROVIDER or "none").lower()
    if selected == "razorpay":
        return RazorpayProvider()
    if selected in _PROVIDER_TYPES:
        return UnconfiguredProvider(selected)
    return UnconfiguredProvider("none")


def billing_status() -> dict[str, Any]:
    provider = get_provider()
    status = provider.status()
    status["message"] = "Payment provider is configured behind the server-side provider interface." if status["configured"] else "No payment provider is configured; Free Mode remains available and no payment can be taken."
    return status


def create_checkout(plan_id: str, amount_inr: int) -> dict[str, Any]:
    provider = get_provider()
    if not provider.configured:
        return {"configured": False, "provider": provider.provider_id, "message": "No payment provider is configured. No payment was taken and no subscription was activated."}
    return {"configured": True, "provider": provider.provider_id, "message": "Use the authenticated billing checkout flow to create a server-side order."}
