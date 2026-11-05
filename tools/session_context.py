"""Request-local chat session context shared by persistence-backed tools."""
from contextvars import ContextVar
from typing import Optional


_session_id: ContextVar[Optional[str]] = ContextVar("chat_session_id", default=None)


def set_current_session(session_id: Optional[str]) -> None:
    _session_id.set(session_id)


def get_current_session() -> Optional[str]:
    return _session_id.get()
