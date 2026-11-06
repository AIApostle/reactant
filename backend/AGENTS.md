# Backend Agent Guidelines

## Backend Scope

- Act as the backend engineer for this application.
- Keep application-code changes inside the backend; do not modify frontend code.
- The root `api contract.md` is the documentation exception when API behavior or frontend integration requirements change.
- If a request requires frontend implementation, explain the backend limitation and ask for a backend-only alternative.

## Security First

- Treat security as a primary requirement in every backend change, not a follow-up.
- Validate and constrain untrusted input at system boundaries; use safe, parameterized operations for data access.
- Enforce authentication and authorization on protected operations, following least privilege.
- Never expose secrets, credentials, or sensitive data in source, logs, or error responses.
- Use secure defaults and avoid weakening existing protections. Add or update tests for security-sensitive behavior.
- Give agents only explicit, least-privilege tools. Enforce business scoping in tool queries, not only in prompts, and default to read-only behavior.
- Connect MCP servers only when required and explicitly trusted/configured; never attach an arbitrary server or expose credentials to agent tools.
- Treat queued agent work as incomplete until its persisted run status and resulting message confirm completion.

## Async, logging, and comments

- Audit every new or changed function for blocking I/O. Use `async def` and
  awaitable clients for network/database work when the surrounding execution
  context is asynchronous. If an existing synchronous SDK must be retained,
  keep the route as a synchronous FastAPI handler (FastAPI runs it in its
  worker pool) or explicitly isolate the blocking call with
  `asyncio.to_thread`; never block an async webhook, WebSocket, or worker loop.
- Do not convert CPU-bound image processing or synchronous helpers to `async`
  merely for appearance. Move expensive CPU-bound work to a worker/thread when
  it can delay concurrent requests.
- Add structured, useful logs at authentication boundaries, external provider
  calls, queue lifecycle transitions, and unexpected failures. Include a
  request/job identifier, operation, outcome, and safe duration/status data.
  Never log access tokens, passwords, webhook secrets, client secrets, raw
  authorization headers, or customer-sensitive payloads.
- Add short comments only where they clarify non-obvious concurrency,
  security, or provider behavior. Do not comment self-evident code.

## Preserve Project Structure

- Treat `backend/main.py` as the application entry point.
- Keep all other backend application files inside `backend/src/`.
- Keep the existing backend folder and module structure intact.
- Put new code in the existing modules that own the relevant responsibility; do not reorganize or rename folders unless explicitly requested.
- Follow established project patterns and update only files needed for the requested change.
- Put shared Pydantic request and response models in `backend/src/schemas/`, organized by domain.
- Keep Supabase database configuration, schema assets, and migrations in `backend/src/supabase/`.
- Database migrations are append-only: never edit or replace a migration that has already been shared or run. For every schema change, add a new, ordered SQL migration file for the user to review and run.
