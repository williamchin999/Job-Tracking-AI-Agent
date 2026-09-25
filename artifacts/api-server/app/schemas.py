from __future__ import annotations

import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

SpreadsheetId = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{10,200}$", min_length=10, max_length=200)
]
CellRange = Annotated[
    str,
    StringConstraints(
        pattern=r"^[A-Za-z0-9_ .!:$'-]{1,120}$",
        min_length=1,
        max_length=120,
        strip_whitespace=True,
    ),
]


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ChatInput(StrictInput):
    message: Annotated[str, StringConstraints(min_length=1, max_length=4000)]


class SearchGmailInput(StrictInput):
    query: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    max_results: int = Field(default=10, ge=1, le=25)


class GetEmailInput(StrictInput):
    email_id: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class FindSpreadsheetInput(StrictInput):
    name: Annotated[str, StringConstraints(min_length=1, max_length=160)]


class ReadSheetInput(StrictInput):
    spreadsheet_id: SpreadsheetId
    range: CellRange


class SheetWriteInput(StrictInput):
    spreadsheet_id: SpreadsheetId
    range: CellRange
    values: list[list[str | int | float | bool | None]] = Field(
        min_length=1, max_length=100
    )

    @field_validator("values")
    @classmethod
    def validate_rows(cls, rows: list[list[object]]) -> list[list[object]]:
        if not rows or any(not row or len(row) > 26 for row in rows):
            raise ValueError("Each write must include rows with 1 to 26 cells.")
        if any(len(str(cell or "")) > 2000 for row in rows for cell in row):
            raise ValueError("A cell value is too long.")
        return rows


def valid_a1_range(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_ .!:$'-]{1,120}", value))