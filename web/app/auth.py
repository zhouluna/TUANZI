"""Shared password for the site. The NVIDIA key never leaves the server."""

from __future__ import annotations

import hmac
import hashlib

from fastapi import HTTPException, Request

from .config import access_password, dev_open

COOKIE = "tuanzi_session"


def session_token(password: str) -> str:
    return hmac.new(password.encode("utf-8"), b"tuanzi-session-v1", hashlib.sha256).hexdigest()


def authorized(request: Request) -> bool:
    password = access_password()
    if not password:
        return dev_open()
    header = request.headers.get("x-tuanzi-password", "")
    if header and hmac.compare_digest(header, password):
        return True
    cookie = request.cookies.get(COOKIE, "")
    return bool(cookie) and hmac.compare_digest(cookie, session_token(password))


def require_access(request: Request) -> None:
    if access_password() and not authorized(request):
        raise HTTPException(status_code=401, detail="需要访问口令")
    if not access_password() and not dev_open():
        # Local reads stay open so the pet can move. Callers that spend the
        # NVIDIA key check nvidia_allowed() separately.
        return


def nvidia_allowed(request: Request) -> bool:
    """Strangers must not be able to spend NVIDIA_API_KEY."""
    if not access_password():
        return dev_open()
    return authorized(request)
