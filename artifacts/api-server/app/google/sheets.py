from __future__ import annotations

from typing import Any

from googleapiclient.discovery import Resource, build
from sqlalchemy.orm import Session

from app.google.auth import get_credentials
from app.schemas import valid_a1_range


def sheets_service(db: Session, user_id: int) -> Resource:
    return build(
        "sheets", "v4", credentials=get_credentials(db, user_id), cache_discovery=False
    )


def drive_service(db: Session, user_id: int) -> Resource:
    return build(
        "drive", "v3", credentials=get_credentials(db, user_id), cache_discovery=False
    )


def find_spreadsheet(
    db: Session, user_id: int, name: str
) -> list[dict[str, str]]:
    escaped = name.replace("\\", "\\\\").replace("'", "\\'")
    result = (
        drive_service(db, user_id)
        .files()
        .list(
            q=f"name contains '{escaped}' and mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false",
            pageSize=20,
            orderBy="modifiedTime desc",
            fields="files(id,name,modifiedTime,webViewLink)",
        )
        .execute()
    )
    return result.get("files", [])


def spreadsheet_title(db: Session, user_id: int, spreadsheet_id: str) -> str:
    return (
        sheets_service(db, user_id)
        .spreadsheets()
        .get(spreadsheetId=spreadsheet_id, fields="properties.title")
        .execute()
        .get("properties", {})
        .get("title", "Google spreadsheet")
    )


def read_sheet(
    db: Session, user_id: int, spreadsheet_id: str, range_name: str
) -> dict[str, Any]:
    if not valid_a1_range(range_name):
        raise ValueError("The spreadsheet range is not valid.")
    return (
        sheets_service(db, user_id)
        .spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=range_name)
        .execute()
    )


def append_sheet_row(
    db: Session,
    user_id: int,
    spreadsheet_id: str,
    range_name: str,
    values: list[list[Any]],
) -> dict[str, Any]:
    if not valid_a1_range(range_name):
        raise ValueError("The spreadsheet range is not valid.")
    return (
        sheets_service(db, user_id)
        .spreadsheets()
        .values()
        .append(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": values},
        )
        .execute()
    )


def update_sheet(
    db: Session,
    user_id: int,
    spreadsheet_id: str,
    range_name: str,
    values: list[list[Any]],
) -> dict[str, Any]:
    if not valid_a1_range(range_name):
        raise ValueError("The spreadsheet range is not valid.")
    return (
        sheets_service(db, user_id)
        .spreadsheets()
        .values()
        .update(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption="USER_ENTERED",
            body={"values": values},
        )
        .execute()
    )