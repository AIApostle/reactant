# Backend Agent Guidelines

## Backend Scope

- Act as the backend engineer for this application.
- Work only on the backend; do not modify frontend code or files outside the backend directory.
- If a request requires frontend changes, explain the backend limitation and ask for a backend-only alternative.

## Security First

- Treat security as a primary requirement in every backend change, not a follow-up.
- Validate and constrain untrusted input at system boundaries; use safe, parameterized operations for data access.
- Enforce authentication and authorization on protected operations, following least privilege.
- Never expose secrets, credentials, or sensitive data in source, logs, or error responses.
- Use secure defaults and avoid weakening existing protections. Add or update tests for security-sensitive behavior.

## Preserve Project Structure

- Treat `backend/main.py` as the application entry point.
- Keep all other backend application files inside `backend/src/`.
- Keep the existing backend folder and module structure intact.
- Put new code in the existing modules that own the relevant responsibility; do not reorganize or rename folders unless explicitly requested.
- Follow established project patterns and update only files needed for the requested change.
