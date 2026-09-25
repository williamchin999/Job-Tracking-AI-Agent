from __future__ import annotations

import json
import logging
from datetime import timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from googleapiclient.errors import HttpError
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, require_csrf
from app.google import sheets
from app.models import ApprovalRequest, Conversation, Message, User, utc_now
from app.agent.tools import _friendly_google_error

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/approvals", tags=["approvals"])


def _serialize(row: ApprovalRequest) -> dict[str, Any]:
    args = json.loads(row.arguments_json)
    created = row.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return {
        "id": row.id,
        "tool_name": row.tool_name,
        "summary": row.summary,
        "spreadsheet_id": args.get("spreadsheet_id"),
        "range": args.get("range"),
        "values": args.get("values", []),
        "status": row.status,
        "created_at": created.isoformat(),
    }


def _append_system_message(db: Session, row: ApprovalRequest, message: str) -> None:
    db.add(
        Message(
            conversation_id=row.conversation_id,
            role="assistant",
            content=message,
        )
    )


def _owned_request(
    db: Session, user: User, request_id: int
) -> ApprovalRequest:
    row = (
        db.query(ApprovalRequest)
        .filter_by(id=request_id, user_id=user.id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Approval request not found.")
    return row


@router.post("/{request_id}/approve", dependencies=[Depends(require_csrf)])
def approve(
    request_id: int, request: Request, db: Session = Depends(get_db)
) -> dict[str, Any]:
    user = get_current_user(request, db)
    row = _owned_request(db, user, request_id)
    if row.status != "pending":
        raise HTTPException(status_code=409, detail=f"This request is already {row.status}.")

    claimed = db.execute(
        update(ApprovalRequest)
        .where(
            ApprovalRequest.id == request_id,
            ApprovalRequest.user_id == user.id,
            ApprovalRequest.status == "pending",
        )
        .values(status="executing")
    )
    db.commit()
    if claimed.rowcount != 1:
        raise HTTPException(status_code=409, detail="This request is already being handled.")
    db.refresh(row)

    try:
        args = json.loads(row.arguments_json)
        if row.tool_name == "append_sheet_row":
            result = sheets.append_sheet_row(
                db,
                user.id,
                args["spreadsheet_id"],
                args["range"],
                args["values"],
            )
            verb = "Added"
        elif row.tool_name == "update_sheet":
            result = sheets.update_sheet(
                db,
                user.id,
                args["spreadsheet_id"],
                args["range"],
                args["values"],
            )
            verb = "Updated"
        else:
            raise ValueError("This write operation is not registered.")
        row.status = "executed"
        row.result_json = json.dumps(
            {
                "updated_range": result.get("updates", {}).get("updatedRange")
                or result.get("tableRange")
                or args["range"]
            }
        )
        row.resolved_at = utc_now()
        row_count = len(args["values"])
        confirmation = (
            f"{verb} {row_count} row{'s' if row_count != 1 else ''} in the approved "
            f"Google Sheets change ({row.summary})."
        )
        _append_system_message(db, row, confirmation)
        db.commit()
        return {"approval": _serialize(row), "message": confirmation}
    except HttpError as exc:
        logger.warning("Google Sheets write failed with HTTP %s", getattr(exc.resp, "status", "unknown"))
        row.status = "failed"
        row.resolved_at = utc_now()
        error = _friendly_google_error(exc)
        row.result_json = json.dumps({"error": error})
        _append_system_message(db, row, f"The approved change was not completed. {error}")
        db.commit()
        raise HTTPException(status_code=502, detail=error) from exc
    except Exception as exc:
        logger.exception("Approved Google Sheets write failed")
        row.status = "failed"
        row.resolved_at = utc_now()
        error = "The approved change could not be completed. Check the sheet permissions and try again."
        row.result_json = json.dumps({"error": error})
        _append_system_message(db, row, error)
        db.commit()
        raise HTTPException(status_code=502, detail=error) from exc


@router.post("/{request_id}/reject", dependencies=[Depends(require_csrf)])
def reject(
    request_id: int, request: Request, db: Session = Depends(get_db)
) -> dict[str, Any]:
    user = get_current_user(request, db)
    row = _owned_request(db, user, request_id)
    if row.status != "pending":
        raise HTTPException(status_code=409, detail=f"This request is already {row.status}.")
    row.status = "rejected"
    row.resolved_at = utc_now()
    message = "Rejected the proposed Google Sheets change. No spreadsheet data was written."
    _append_system_message(db, row, message)
    db.commit()
    return {"approval": _serialize(row), "message": message}