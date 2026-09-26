---
name: Python artifact runtime
description: Environment-specific constraints for running the Python API artifact on Replit.
---

Managed development service commands run with the artifact directory as their working directory, while the production run command is evaluated from the repository root. Python module imports therefore need different app-dir paths in development and production.

**Why:** A repository-relative development app-dir failed because the managed service had already changed into `artifacts/api-server`; using `.` in production then failed because production starts from the repository root.

**How to apply:** Use `--app-dir .` for the development workflow and `--app-dir artifacts/api-server` for the production run command unless the artifact runner's working directories change.

The workspace may expose a runtime-managed `DATABASE_URL` for PostgreSQL even when the app is designed around SQLite. Use a clearly named app-specific override for an optional database migration instead of silently selecting the managed URL without its driver.

**Why:** Selecting the automatic PostgreSQL URL made SQLAlchemy import `psycopg`, which was not part of the requested SQLite stack or installed dependencies.

**How to apply:** Default this app to SQLite and only opt into another database through an explicit project-specific environment variable after adding and verifying its driver.