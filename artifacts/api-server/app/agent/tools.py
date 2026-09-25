from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import Any

from googleapiclient.errors import HttpError
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.google import gmail, sheets
from app.models import ApprovalRequest, utc_now
from app.schemas import (
    FindSpreadsheetInput,
    GetEmailInput,
    ReadSheetInput,
    SearchGmailInput,
    SheetWriteInput,
)

logger = logging.getLogger(__name__)

TOOL_DECLARATIONS = [
    {
        "name": "search_gmail",
        "description": "Search the connected user's Gmail and return message summaries.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "A Gmail search query."},
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of messages, from 1 to 25.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_email",
        "description": "Read the body and headers of one Gmail message by its id.",
        "parameters": {
            "type": "object",
            "properties": {
                "email_id": {"type": "string", "description": "Gmail message id."}
            },
            "required": ["email_id"],
        },
    },
    {
        "name": "find_spreadsheet",
        "description": "Find Google spreadsheets by name in the connected user's Drive.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Spreadsheet name to search for."}
            },
            "required": ["name"],
        },
    },
    {
        "name": "read_sheet",
        "description": "Read values from a Google spreadsheet range.",
        "parameters": {
            "type": "object",
            "properties": {
                "spreadsheet_id": {"type": "string"},
                "range": {"type": "string", "description": "A1 notation, e.g. A1:H100."},
            },
            "required": ["spreadsheet_id", "range"],
        },
    },
    {
        "name": "append_sheet_row",
        "description": "Propose appending rows to a Google sheet. This creates an approval request; it does not write data.",
        "parameters": {
            "type": "object",
            "properties": {
                "spreadsheet_id": {"type": "string"},
                "range": {"type": "string", "description": "A1 range identifying the destination columns."},
                "values": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "string"}},
                    "description": "Rows of cell values to append.",
                },
            },
            "required": ["spreadsheet_id", "range", "values"],
        },
    },
    {
        "name": "update_sheet",
        "description": "Propose updating a Google sheet range. This creates an approval request; it does not write data.",
        "parameters": {
            "type": "object",
            "properties": {
                "spreadsheet_id": {"type": "string"},
                "range": {"type": "string", "description": "A1 notation of cells to update."},
                "values": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "string"}},
                    "description": "Rows of cell values to write.",
                },
            },
            "required": ["spreadsheet_id", "range", "values"],
        },
    },
]

READ_ARG_MODELS = {
    "search_gmail": SearchGmailInput,
    "get_email": GetEmailInput,
    "find_spreadsheet": FindSpreadsheetInput,
    "read_sheet": ReadSheetInput,
}
WRITE_TOOLS = {"append_sheet_row", "update_sheet"}
REGISTERED_TOOLS = set(READ_ARG_MODELS) | WRITE_TOOLS
WRITE_REQUEST_PATTERN = re.compile(
    r"\b(add|append|update|write|insert|save|log|record|enter)\b"
    r".{0,100}\b(spreadsheet|sheet|application|applications|row|rows|opportunit)",
    re.IGNORECASE,
)
WRITE_TARGET_FIRST_PATTERN = re.compile(
    r"\b(spreadsheet|sheet|application|applications|row|rows)\b"
    r".{0,100}\b(add|append|update|write|insert|save|log|record|enter)\b",
    re.IGNORECASE,
)


def user_explicitly_requested_write(message: str) -> bool:
    return bool(
        WRITE_REQUEST_PATTERN.search(message) or WRITE_TARGET_FIRST_PATTERN.search(message)
    )


def _validate_tool_args(name: str, args: dict[str, Any]) -> Any:
    model = READ_ARG_MODELS.get(name)
    if name in WRITE_TOOLS:
        model = SheetWriteInput
    if model is None:
        raise ValueError("This tool is not registered.")
    return model.model_validate(args)


def _friendly_google_error(exc: HttpError) -> str:
    status = getattr(exc.resp, "status", None)
    if status == 401:
        return "Google sign-in expired. Disconnect and reconnect your Google account."
    if status == 403:
        return "Google denied this request. Check that Gmail, Sheets, and Drive metadata scopes are enabled."
    if status == 404:
        return "Google could not find that message, spreadsheet, or range."
    if status == 429:
        return "Google rate limit reached. Wait a moment and try again."
    return "Google could not complete the request. Check the Google API permissions and try again."


def stage_write(
    db: Session,
    user_id: int,
    conversation_id: int,
    tool_name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    parsed = _validate_tool_args(tool_name, args)
    title = sheets.spreadsheet_title(db, user_id, parsed.spreadsheet_id)
    rows = len(parsed.values)
    action = "Append" if tool_name == "append_sheet_row" else "Update"
    record = ApprovalRequest(
        user_id=user_id,
        conversation_id=conversation_id,
        tool_name=tool_name,
        arguments_json=json.dumps(parsed.model_dump(), ensure_ascii=False),
        summary=f"{action} {rows} row{'s' if rows != 1 else ''} in “{title}” ({parsed.range})",
        status="pending",
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return {
        "status": "pending_approval",
        "approval_id": record.id,
        "summary": record.summary,
        "row_count": rows,
    }


def execute_read_tool(
    db: Session, user_id: int, name: str, raw_args: dict[str, Any]
) -> dict[str, Any]:
    if name not in READ_ARG_MODELS:
        raise ValueError("Only registered read tools can run automatically.")
    parsed = _validate_tool_args(name, raw_args)
    if name == "search_gmail":
        return {
            "messages": gmail.search_gmail(
                db, user_id, parsed.query, parsed.max_results
            )
        }
    if name == "get_email":
        return gmail.get_email(db, user_id, parsed.email_id)
    if name == "find_spreadsheet":
        return {"spreadsheets": sheets.find_spreadsheet(db, user_id, parsed.name)}
    if name == "read_sheet":
        return sheets.read_sheet(db, user_id, parsed.spreadsheet_id, parsed.range)
    raise ValueError("This read tool is not registered.")


def call_tool(
    db: Session,
    user_id: int,
    conversation_id: int,
    name: str,
    raw_args: dict[str, Any],
    allow_write: bool,
    on_activity: Callable[[str, dict[str, Any], dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if name not in REGISTERED_TOOLS:
        raise ValueError("The model requested a tool that is not registered.")
    if name in WRITE_TOOLS:
        if not allow_write:
            return {
                "status": "blocked",
                "message": "The user's current message did not explicitly request a spreadsheet change. Ask them before proposing a write.",
            }
        result = stage_write(db, user_id, conversation_id, name, raw_args)
        if on_activity:
            on_activity(name, raw_args, result)
        return result

    try:
        result = execute_read_tool(db, user_id, name, raw_args)
    except ValidationError as exc:
        result = {"error": "Invalid tool arguments.", "details": exc.errors(include_url=False)}
    except HttpError as exc:
        logger.warning("Google API request failed with HTTP %s", getattr(exc.resp, "status", "unknown"))
        result = {"error": _friendly_google_error(exc)}
    except (ValueError, RuntimeError) as exc:
        result = {"error": str(exc)}
    except Exception:
        logger.exception("Registered Google read tool failed: %s", name)
        result = {"error": "Google could not complete this read request."}
    if on_activity:
        on_activity(name, raw_args, result)
    return result