from __future__ import annotations

import json
import logging
from datetime import timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from googleapiclient.errors import HttpError
from sqlalchemy.orm import Session

from app.agent.agent import AgentSetupError, run_agent
from app.config import settings
from app.dependencies import get_current_user, get_db, require_csrf
from app.google.auth import oauth_configured
from app.models import ApprovalRequest, Conversation, Message, User
from app.schemas import ChatInput

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def approval_payload(row: ApprovalRequest) -> dict[str, Any]:
    arguments = json.loads(row.arguments_json)
    return {
        "id": row.id,
        "tool_name": row.tool_name,
        "summary": row.summary,
        "spreadsheet_id": arguments.get("spreadsheet_id"),
        "range": arguments.get("range"),
        "values": arguments.get("values", []),
        "status": row.status,
        "created_at": _iso(row.created_at),
        "resolved_at": _iso(row.resolved_at),
    }


def _conversation_for(db: Session, user: User, request: Request) -> Conversation:
    current_id = request.session.get("conversation_id")
    conversation = (
        db.query(Conversation)
        .filter_by(id=current_id, user_id=user.id)
        .one_or_none()
        if isinstance(current_id, int)
        else None
    )
    if conversation is None:
        conversation = Conversation(user_id=user.id)
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        request.session["conversation_id"] = conversation.id
    return conversation


@router.get("/status")
def status_payload(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    user_id = request.session.get("user_id")
    user = db.get(User, user_id) if isinstance(user_id, int) else None
    return {
        "google": {
            "configured": oauth_configured(),
            "connected": bool(user and user.credential),
            "email": user.email if user else None,
            "redirect_uri": str(request.url_for("google_callback")),
        },
        "gemini": {"configured": bool(settings.gemini_api_key)},
        "csrf_token": request.session.get("csrf_token"),
    }


@router.get("/history")
def history(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    user_id = request.session.get("user_id")
    if not isinstance(user_id, int):
        return {"messages": [], "approvals": []}
    user = db.get(User, user_id)
    if user is None:
        return {"messages": [], "approvals": []}
    conversation = _conversation_for(db, user, request)
    messages = (
        db.query(Message)
        .filter_by(conversation_id=conversation.id)
        .order_by(Message.id.asc())
        .limit(500)
        .all()
    )
    approvals = (
        db.query(ApprovalRequest)
        .filter_by(conversation_id=conversation.id)
        .order_by(ApprovalRequest.id.asc())
        .all()
    )
    return {
        "messages": [
            {
                "id": row.id,
                "role": row.role,
                "content": row.content,
                "metadata": json.loads(row.metadata_json) if row.metadata_json else None,
                "created_at": _iso(row.created_at),
            }
            for row in messages
            if row.role in {"user", "assistant", "activity"}
        ],
        "approvals": [approval_payload(row) for row in approvals],
    }


@router.post("/chat", dependencies=[Depends(require_csrf)])
def send_message(
    payload: ChatInput,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    user = get_current_user(request, db)
    conversation = _conversation_for(db, user, request)
    message = payload.message.strip()
    user_message = Message(
        conversation_id=conversation.id,
        role="user",
        content=message,
    )
    if conversation.title == "New conversation":
        conversation.title = message[:120]
    db.add(user_message)
    db.commit()

    def record_tool_activity(
        name: str, args: dict[str, Any], result: dict[str, Any]
    ) -> None:
        labels = {
            "search_gmail": "Searching Gmail",
            "get_email": "Reading a relevant email",
            "find_spreadsheet": "Finding your spreadsheet",
            "read_sheet": "Reading spreadsheet rows",
            "append_sheet_row": "Preparing proposed row additions",
            "update_sheet": "Preparing a proposed spreadsheet update",
        }
        label = labels.get(name, "Using a connected source")
        if name == "search_gmail":
            count = len(result.get("messages", []))
            detail = f"{label} · {count} message{'s' if count != 1 else ''} found"
        elif name == "find_spreadsheet":
            count = len(result.get("spreadsheets", []))
            detail = f"{label} · {count} match{'es' if count != 1 else ''}"
        elif name == "read_sheet":
            count = len(result.get("values", []))
            detail = f"{label} · {count} row{'s' if count != 1 else ''} read"
        elif name in {"append_sheet_row", "update_sheet"}:
            detail = "Proposed spreadsheet changes are ready for review"
        else:
            subject = result.get("subject")
            detail = f"{label} · {subject}" if subject else f"{label} · complete"
        if result.get("error"):
            detail = f"{label} · needs attention"
        db.add(
            Message(
                conversation_id=conversation.id,
                role="activity",
                content=detail,
            )
        )
        db.commit()

    try:
        answer, approval_ids = run_agent(
            db=db,
            user_id=user.id,
            conversation_id=conversation.id,
            current_message=message,
            on_activity=record_tool_activity,
        )
    except AgentSetupError as exc:
        answer = str(exc)
        approval_ids = []
        status_code = 503
    except HttpError as exc:
        logger.warning("Google API failure during agent request: HTTP %s", getattr(exc.resp, "status", "unknown"))
        answer = "Google could not complete that request. Check your Google API permissions and try again."
        approval_ids = []
        status_code = 502
    except Exception:
        logger.exception("Gemini request failed")
        answer = "Gemini could not complete that request. Check GEMINI_API_KEY, model access, and API quota."
        approval_ids = []
        status_code = 502
    else:
        status_code = 200

    assistant_message = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=answer,
        metadata_json=json.dumps({"approval_ids": approval_ids}),
    )
    db.add(assistant_message)
    db.commit()
    approvals = (
        db.query(ApprovalRequest)
        .filter(ApprovalRequest.id.in_(approval_ids), ApprovalRequest.user_id == user.id)
        .all()
        if approval_ids
        else []
    )
    return {
        "message": {
            "id": assistant_message.id,
            "role": "assistant",
            "content": answer,
            "created_at": _iso(assistant_message.created_at),
        },
        "approvals": [approval_payload(row) for row in approvals],
        "status": status_code,
    }