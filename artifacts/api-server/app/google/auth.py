from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from sqlalchemy.orm import Session

from app.config import settings
from app.models import GoogleCredential, User, utc_now

GOOGLE_SCOPES = [
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
]


def oauth_configured() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def make_flow(redirect_uri: str, state: str | None = None) -> Flow:
    if not oauth_configured():
        raise RuntimeError("Google OAuth is not configured.")
    client_config = {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }
    flow = Flow.from_client_config(
        client_config, scopes=GOOGLE_SCOPES, state=state, redirect_uri=redirect_uri
    )
    return flow


def _cipher(user_id: int) -> Fernet:
    digest = hashlib.sha256(
        f"google-token:{user_id}:{settings.session_secret}".encode("utf-8")
    ).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_token_json(user_id: int, token_json: str) -> str:
    return _cipher(user_id).encrypt(token_json.encode("utf-8")).decode("ascii")


def decrypt_token_json(user_id: int, encrypted: str) -> str:
    try:
        return _cipher(user_id).decrypt(encrypted.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise RuntimeError(
            "Stored Google credentials could not be decrypted. Reconnect the Google account."
        ) from exc


def save_credentials(db: Session, user: User, credentials: Credentials) -> None:
    existing = db.query(GoogleCredential).filter_by(user_id=user.id).one_or_none()
    token_json = credentials.to_json()
    encrypted = encrypt_token_json(user.id, token_json)
    if existing is None:
        db.add(
            GoogleCredential(
                user_id=user.id,
                encrypted_token_json=encrypted,
                updated_at=utc_now(),
            )
        )
    else:
        existing.encrypted_token_json = encrypted
        existing.updated_at = utc_now()
    db.commit()


def get_credentials(db: Session, user_id: int) -> Credentials:
    record = db.query(GoogleCredential).filter_by(user_id=user_id).one_or_none()
    if record is None:
        raise RuntimeError("Connect your Google account to use Gmail and Sheets.")
    raw = decrypt_token_json(user_id, record.encrypted_token_json)
    credentials = Credentials.from_authorized_user_info(
        json.loads(raw), scopes=GOOGLE_SCOPES
    )
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(GoogleRequest())
        save_credentials(db, db.get(User, user_id), credentials)
    if not credentials.valid:
        raise RuntimeError("Google access expired. Disconnect and reconnect your account.")
    return credentials


def public_google_setup() -> dict[str, Any]:
    return {
        "configured": oauth_configured(),
        "redirect_uri": settings.google_redirect_uri,
    }