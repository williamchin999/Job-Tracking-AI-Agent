# Threadline API Server

Threadline is a FastAPI/Jinja2 personal Gmail and Google Sheets agent. It uses Gemini function calling for read actions and requires an explicit approval before any spreadsheet write.

## Local development

From the repository root:

```bash
uvicorn app.main:app --app-dir artifacts/api-server --reload
```

Configure the variables in `.env` or Replit Secrets. Never commit `.env`.

Google OAuth requires:

1. A Google OAuth web application client.
2. Gmail API, Google Sheets API, and Google Drive API enabled.
3. The exact `/auth/google/callback` URL registered in Google Cloud.

The app reports missing setup on the login page instead of fabricating connected data.

## Safety boundary

Gemini receives only the registered Gmail, Sheets, and Drive tools. Spreadsheet append and update calls create pending approval records. The Google Sheets write happens only in the approval endpoint after the user clicks Approve.