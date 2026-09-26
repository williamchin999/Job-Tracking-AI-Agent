# Threadline Personal AI Agent

Threadline is a private Gmail and Google Sheets workbench that uses Gemini to find, summarize, and prepare spreadsheet changes for explicit approval.

## Run & Operate

- `uvicorn app.main:app --app-dir artifacts/api-server --reload` — run the Python app locally
- `python -m compileall -q artifacts/api-server/app` — check Python syntax
- `python -m pytest` — run tests when present
- The managed artifact workflow runs Uvicorn on the injected `PORT`.
- Required secrets: `SESSION_SECRET`, `GEMINI_API_KEY`, `GOOGLE_CLIENT_ID`, and `GOOGLE_CLIENT_SECRET`.
- Required development environment variable: `GOOGLE_REDIRECT_URI`.

## Stack

- Python 3.13, FastAPI, Uvicorn, Jinja2, and vanilla JavaScript
- SQLite with SQLAlchemy
- Google OAuth plus Gmail, Sheets, and Drive APIs
- Gemini function calling through the user's own `GEMINI_API_KEY`

## Where things live

- `artifacts/api-server/app/main.py` — FastAPI app, page routes, and lifespan
- `artifacts/api-server/app/routes/` — OAuth, chat, and approval endpoints
- `artifacts/api-server/app/agent/` — Gemini prompt, tool declarations, and execution loop
- `artifacts/api-server/app/google/` — encrypted OAuth credentials and Google API clients
- `artifacts/api-server/app/templates/` — Jinja2 pages
- `artifacts/api-server/app/static/` — responsive CSS and vanilla JavaScript
- `artifacts/api-server/app/models.py` — SQLite/SQLAlchemy data model

## Architecture decisions

- Google OAuth belongs to the app so each user authorizes their own Gmail and Sheets access.
- OAuth token JSON is encrypted with a key derived from `SESSION_SECRET` and the user id before storage.
- Gmail and Sheets writes are separate registered tools and are staged as approval records first; only approval routes call write APIs.
- Sheet writes are omitted from Gemini's available tools unless the current user message explicitly asks for a spreadsheet change.
- The app uses SQLite to match the requested stack; production deployments should use persistent database storage if restart-safe history is required.

## Product

Users connect Google, ask Threadline to search Gmail or inspect Sheets, and review proposed spreadsheet changes in the workbench before approving or rejecting them.

## User preferences

- Use the user's own Gemini API key.
- Keep spreadsheet writes approval-gated.

## Gotchas

- Add the exact development callback URL shown on `/login` to the Google OAuth client.
- Enable Gmail API, Google Sheets API, and Google Drive API in the same Google Cloud project.
- Do not expose OAuth credentials or Gemini keys in source, logs, or chat.

## Pointers

- Python dependency declarations are in the root `pyproject.toml`; `uv.lock` records the installed environment.
- The API artifact service definition is managed through `artifacts/api-server/.replit-artifact/artifact.toml`.