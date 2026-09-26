---
name: Python artifact runtime
description: Environment-specific constraints for running the Python API artifact on Replit.
---

Managed artifact service commands run with the artifact directory as their working directory. Python module imports should therefore use the local app directory rather than appending the repository-relative artifact path.

**Why:** A repository-relative `--app-dir artifacts/api-server` caused Uvicorn to fail because the managed service had already changed into `artifacts/api-server`.

**How to apply:** Keep the service command's app directory as `.` unless the workflow's working directory is explicitly changed.

The workspace may expose a runtime-managed `DATABASE_URL` for PostgreSQL even when the app is designed around SQLite. Use a clearly named app-specific override for an optional database migration instead of silently selecting the managed URL without its driver.

**Why:** Selecting the automatic PostgreSQL URL made SQLAlchemy import `psycopg`, which was not part of the requested SQLite stack or installed dependencies.

**How to apply:** Default this app to SQLite and only opt into another database through an explicit project-specific environment variable after adding and verifying its driver.