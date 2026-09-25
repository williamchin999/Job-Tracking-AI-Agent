from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.database import init_db
from app.dependencies import ensure_csrf_token
from app.google.auth import oauth_configured
from app.routes import actions, auth, chat

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

APP_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Threadline Personal AI Agent",
    description="A private assistant for Gmail and Google Sheets with approval-gated writes.",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    session_cookie="threadline_session",
    max_age=60 * 60 * 24 * 14,
    same_site="lax",
    https_only=settings.secure_cookies,
)
app.mount(
    "/static",
    StaticFiles(directory=str(APP_DIR / "static")),
    name="static",
)
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(actions.router)


def _google_error_message(code: str | None) -> str | None:
    if not code:
        return None
    messages = {
        "setup": "Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in Replit Secrets before connecting Google.",
        "state": "The Google sign-in check expired. Start the connection again.",
        "redirect": "Google rejected the callback address. Add the exact callback URL to your Google OAuth client and set GOOGLE_REDIRECT_URI.",
        "authorization": "Google could not finish sign-in. Check the OAuth consent screen, enabled APIs, and requested scopes.",
    }
    return messages.get(code, "Google sign-in could not be completed.")


def _render_page(request: Request, template_name: str, page_title: str) -> HTMLResponse:
    csrf_token = ensure_csrf_token(request)
    context = {
        "request": request,
        "page_title": page_title,
        "csrf_token": csrf_token,
        "google_configured": oauth_configured(),
        "gemini_configured": bool(settings.gemini_api_key),
        "google_email": request.session.get("user_email"),
        "google_error": _google_error_message(request.query_params.get("google_error")),
        "redirect_uri": settings.google_redirect_uri or str(request.url_for("google_callback")),
    }
    return templates.TemplateResponse(request, template_name, context)


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return _render_page(request, "index.html", "Threadline · Personal AI Agent")


@app.get("/login", response_class=HTMLResponse)
def login(request: Request) -> HTMLResponse:
    return _render_page(request, "login.html", "Connect Google · Threadline")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/healthz")
def legacy_health() -> dict[str, str]:
    return {"status": "ok"}


@app.exception_handler(404)
async def not_found(_: Request, __: Exception) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "Not found."})