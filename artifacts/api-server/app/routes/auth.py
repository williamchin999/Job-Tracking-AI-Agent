from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
from sqlalchemy.orm import Session

from app.config import settings
from app.dependencies import get_db, require_csrf
from app.google.auth import make_flow, oauth_configured, save_credentials
from app.models import Conversation, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


def callback_uri(request: Request) -> str:
    return settings.google_redirect_uri or str(request.url_for("google_callback"))


@router.get("/google")
def start_google_oauth(request: Request) -> RedirectResponse:
    if not oauth_configured():
        return RedirectResponse(url="/login?google_error=setup", status_code=303)
    state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = state
    flow = make_flow(callback_uri(request), state=state)
    url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return RedirectResponse(url=url, status_code=302)


@router.get("/google/callback", name="google_callback")
def finish_google_oauth(
    request: Request, db: Session = Depends(get_db)
) -> RedirectResponse:
    returned_state = request.query_params.get("state", "")
    expected_state = request.session.pop("oauth_state", "")
    if not expected_state or not secrets.compare_digest(expected_state, returned_state):
        return RedirectResponse(url="/login?google_error=state", status_code=303)
    if request.query_params.get("error"):
        return RedirectResponse(url="/login?google_error=authorization", status_code=303)

    try:
        flow = make_flow(callback_uri(request), state=expected_state)
        flow.fetch_token(authorization_response=str(request.url))
        credentials = flow.credentials
        identity = id_token.verify_oauth2_token(
            credentials.id_token, GoogleRequest(), settings.google_client_id
        )
        email = str(identity.get("email", "")).strip().lower()
        if not email:
            raise ValueError("Google did not return an account email.")
        user = db.query(User).filter_by(email=email).one_or_none()
        if user is None:
            user = User(email=email, display_name=identity.get("name"))
            db.add(user)
            db.flush()
        else:
            user.display_name = identity.get("name") or user.display_name
        db.commit()
        save_credentials(db, user, credentials)

        conversation_id = request.session.get("conversation_id")
        conversation = (
            db.query(Conversation)
            .filter_by(id=conversation_id, user_id=user.id)
            .one_or_none()
            if isinstance(conversation_id, int)
            else None
        )
        if conversation is None:
            conversation = Conversation(user_id=user.id)
            db.add(conversation)
            db.commit()
            db.refresh(conversation)
        request.session.clear()
        request.session.update(
            {
                "user_id": user.id,
                "user_email": user.email,
                "conversation_id": conversation.id,
                "csrf_token": secrets.token_urlsafe(32),
            }
        )
        return RedirectResponse(url="/", status_code=303)
    except Exception as exc:
        logger.exception("Google OAuth callback failed")
        message = "authorization"
        if "redirect_uri_mismatch" in str(exc).lower():
            message = "redirect"
        return RedirectResponse(url=f"/login?google_error={message}", status_code=303)


@router.post("/disconnect", dependencies=[Depends(require_csrf)])
def disconnect_google(request: Request, db: Session = Depends(get_db)) -> dict[str, bool]:
    user_id = request.session.get("user_id")
    if isinstance(user_id, int):
        user = db.get(User, user_id)
        if user and user.credential:
            db.delete(user.credential)
            db.commit()
    request.session.clear()
    return {"disconnected": True}