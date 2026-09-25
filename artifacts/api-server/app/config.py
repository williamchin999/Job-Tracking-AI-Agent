from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent
SERVER_DIR = APP_DIR.parent
PROJECT_ROOT = SERVER_DIR.parent.parent
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(SERVER_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str | None
    gemini_model: str
    google_client_id: str | None
    google_client_secret: str | None
    google_redirect_uri: str | None
    session_secret: str
    database_url: str
    secure_cookies: bool


def load_settings() -> Settings:
    session_secret = os.getenv("SECRET_KEY") or os.getenv("SESSION_SECRET")
    if not session_secret:
        raise RuntimeError(
            "Set SECRET_KEY (or the Replit SESSION_SECRET) before starting the app."
        )

    return Settings(
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
        google_client_id=os.getenv("GOOGLE_CLIENT_ID"),
        google_client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        google_redirect_uri=os.getenv("GOOGLE_REDIRECT_URI") or None,
        session_secret=session_secret,
        database_url=os.getenv("DATABASE_URL", "sqlite:///./agent.db"),
        secure_cookies=os.getenv("APP_ENV", "development").lower() != "development",
    )


settings = load_settings()