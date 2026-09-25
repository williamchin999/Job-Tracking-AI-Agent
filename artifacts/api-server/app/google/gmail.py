from __future__ import annotations

import base64
from email.utils import parseaddr
from typing import Any

from googleapiclient.discovery import Resource, build
from sqlalchemy.orm import Session

from app.google.auth import get_credentials


def gmail_service(db: Session, user_id: int) -> Resource:
    return build("gmail", "v1", credentials=get_credentials(db, user_id), cache_discovery=False)


def search_gmail(
    db: Session, user_id: int, query: str, max_results: int
) -> list[dict[str, Any]]:
    service = gmail_service(db, user_id)
    response = (
        service
        .users()
        .messages()
        .list(userId="me", q=query, maxResults=max_results)
        .execute()
    )
    output: list[dict[str, Any]] = []
    for item in response.get("messages", []):
        message = (
            service
            .users()
            .messages()
            .get(userId="me", id=item["id"], format="metadata", metadataHeaders=["From", "Subject", "Date"])
            .execute()
        )
        headers = {
            header["name"].lower(): header["value"]
            for header in message.get("payload", {}).get("headers", [])
        }
        output.append(
            {
                "id": item["id"],
                "thread_id": item.get("threadId"),
                "sender": headers.get("from", ""),
                "subject": headers.get("subject", "(no subject)"),
                "date": headers.get("date", ""),
                "snippet": message.get("snippet", ""),
            }
        )
    return output


def _decode_body(payload: dict[str, Any]) -> str:
    plain_parts: list[str] = []
    html_parts: list[str] = []

    def collect(part: dict[str, Any]) -> None:
        body = part.get("body", {}).get("data")
        mime_type = part.get("mimeType", "")
        if body and mime_type in {"text/plain", "text/html"}:
            try:
                decoded = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode(
                    "utf-8", errors="replace"
                )
            except (ValueError, UnicodeError):
                decoded = ""
            (plain_parts if mime_type == "text/plain" else html_parts).append(decoded)
        for child in part.get("parts", []):
            collect(child)

    collect(payload)
    if plain_parts:
        return "\n".join(plain_parts)[:12000]

    if html_parts:
        from html.parser import HTMLParser

        class TextExtractor(HTMLParser):
            def __init__(self) -> None:
                super().__init__(convert_charrefs=True)
                self.text: list[str] = []

            def handle_data(self, data: str) -> None:
                cleaned = data.strip()
                if cleaned:
                    self.text.append(cleaned)

        parser = TextExtractor()
        parser.feed("\n".join(html_parts))
        return " ".join(parser.text)[:12000]
    return ""


def get_email(db: Session, user_id: int, email_id: str) -> dict[str, Any]:
    message = (
        gmail_service(db, user_id)
        .users()
        .messages()
        .get(userId="me", id=email_id, format="full")
        .execute()
    )
    headers = {
        header["name"].lower(): header["value"]
        for header in message.get("payload", {}).get("headers", [])
    }
    sender_name, sender_email = parseaddr(headers.get("from", ""))
    return {
        "id": message["id"],
        "thread_id": message.get("threadId"),
        "sender": sender_name or sender_email or headers.get("from", ""),
        "sender_email": sender_email,
        "recipient": headers.get("to", ""),
        "subject": headers.get("subject", "(no subject)"),
        "date": headers.get("date", ""),
        "body": _decode_body(message.get("payload", {})),
    }