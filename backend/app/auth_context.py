from __future__ import annotations

from contextvars import ContextVar
from typing import Any

_current_user_id: ContextVar[str | None] = ContextVar("clipforge_current_user_id", default=None)
_current_session_id: ContextVar[str | None] = ContextVar("clipforge_current_session_id", default=None)


def set_context(user_id: str | None, session_id: str | None = None) -> tuple[Any, Any]:
    return _current_user_id.set(user_id), _current_session_id.set(session_id)


def reset_context(tokens: tuple[Any, Any]) -> None:
    _current_user_id.reset(tokens[0])
    _current_session_id.reset(tokens[1])


def current_user_id() -> str | None:
    return _current_user_id.get()


def current_session_id() -> str | None:
    return _current_session_id.get()
