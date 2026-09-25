from __future__ import annotations

import secrets
from collections.abc import Generator

from fastapi import Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import User


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(request: Request, db: Session) -> User:
    user_id = request.session.get("user_id")
    if not isinstance(user_id, int):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Connect your Google account to continue.",
        )
    user = db.get(User, user_id)
    if user is None:
        request.session.clear()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your session has expired. Connect your Google account again.",
        )
    return user


def ensure_csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not isinstance(token, str) or len(token) < 32:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def require_csrf(
    request: Request,
    x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> None:
    expected = request.session.get("csrf_token")
    if (
        not isinstance(expected, str)
        or not isinstance(x_csrf_token, str)
        or not secrets.compare_digest(expected, x_csrf_token)
    ):
        raise HTTPException(
            status_code=403,
            detail="This request could not be verified. Refresh and try again.",
        )