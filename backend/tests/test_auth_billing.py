import hashlib
import hmac

from app import auth_db
from app.billing import RazorpayProvider, get_provider


def test_password_hash_is_not_plaintext_and_verifies():
    encoded = auth_db.hash_password("SecurePass123")
    assert encoded != "SecurePass123"
    assert auth_db.verify_password("SecurePass123", encoded)
    assert not auth_db.verify_password("wrong-password", encoded)


def test_razorpay_signature_verification_is_server_side(monkeypatch):
    monkeypatch.setattr("app.billing.RAZORPAY_KEY_ID", "rzp_test_example")
    monkeypatch.setattr("app.billing.RAZORPAY_KEY_SECRET", "server-secret")
    monkeypatch.setattr("app.billing.RAZORPAY_WEBHOOK_SECRET", "webhook-secret")
    provider = RazorpayProvider()
    payment_signature = hmac.new(b"server-secret", b"order_123|pay_123", hashlib.sha256).hexdigest()
    webhook_body = b'{"event":"payment.captured"}'
    webhook_signature = hmac.new(b"webhook-secret", webhook_body, hashlib.sha256).hexdigest()
    assert provider.configured
    assert provider.verify_payment("order_123", "pay_123", payment_signature)
    assert not provider.verify_payment("order_123", "pay_123", "bad")
    assert provider.verify_webhook(webhook_body, webhook_signature)
    assert not provider.verify_webhook(webhook_body, "bad")


def test_other_gateways_are_explicitly_unconfigured():
    provider = get_provider("stripe")
    assert provider.provider_id == "stripe"
    assert provider.configured is False
