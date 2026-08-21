from __future__ import annotations

import base64
import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet

from ..config import STORAGE_ROOT


class TokenStore:
    """Encrypt OAuth tokens at rest using a local key or TOKEN_ENCRYPTION_KEY."""

    def __init__(self) -> None:
        self.key_path = STORAGE_ROOT / ".token_key"
        self._fernet = Fernet(self._load_key())

    def _load_key(self) -> bytes:
        configured = os.getenv("TOKEN_ENCRYPTION_KEY", "").strip()
        if configured:
            try:
                Fernet(configured.encode())
                return configured.encode()
            except Exception as exc:
                raise RuntimeError("TOKEN_ENCRYPTION_KEY must be a valid Fernet key.") from exc
        if self.key_path.exists():
            key = self.key_path.read_bytes().strip()
            Fernet(key)
            return key
        key = Fernet.generate_key()
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        self.key_path.write_bytes(key)
        try:
            self.key_path.chmod(0o600)
        except OSError:
            pass
        return key

    def encrypt(self, value: str | None) -> str | None:
        if not value:
            return None
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str | None) -> str | None:
        if not value:
            return None
        return self._fernet.decrypt(value.encode()).decode()


_store: TokenStore | None = None


def get_token_store() -> TokenStore:
    global _store
    if _store is None:
        _store = TokenStore()
    return _store
