# Reactant Backend

FastAPI backend using Supabase Auth, Postgres, Storage, and the Supabase Python
SDK. The application entry point is `main.py`; application modules live under
`src/`.

## Local setup

Use Python 3.11 and `uv`:

```sh
uv sync
cp .env.example .env
uv run uvicorn main:app --reload
```

The `.env.example` file is a template only. Keep real credentials in the
ignored `.env` file and never commit or log them. Required configuration:

- `SUPABASE_URL`
- `SUPABASE_PERISHABLE_KEY` (the Supabase publishable/anon key used by the
  user-scoped API client). `SUPABASE_PUBLISHABLE_KEY` and
  `SUPABASE_ANON_KEY` are accepted aliases for hosted deployments.

Additional configuration:

- `SUPABASE_SECRET_KEY` — service-role/secret key, only for backend service
  operations. Never expose it to the frontend.
- `CREDENTIALS_ENCRYPTION_KEY` — Fernet key required to store integration
  credentials. Generate one with
  `uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
- `ALLOWED_WEB_ORIGINS` — comma-separated exact browser origins for CORS and
  WebSocket origin checks.
- `PUBLIC_API_BASE_URL` — public HTTPS backend URL used for provider webhooks,
  such as `https://reactant.onrender.com`.
- `INVITATION_DELIVERY_URL` and `INVITATION_DELIVERY_TOKEN` — HTTPS invitation
  delivery webhook.
- `INTERNAL_SERVICE_TOKEN` — authentication for trusted internal agent calls.
- `STRANDS_AGENT_ENABLED=true` — opt in to the Strands background worker and
-  owner-assistant runtime. Requires `SUPABASE_SECRET_KEY` and
  `OPENROUTER_API_KEY`. Keep disabled until these credentials and the Supabase
  migration are configured.
- `OPENROUTER_API_KEY` — backend-only OpenRouter API key used by Strands'
  OpenAI-compatible provider. Do not expose it to the frontend.
- `openrouter_api_key` is accepted as an equivalent environment variable name.
- `OPENROUTER_MODEL_ID` — optional model ID; defaults to `openrouter/free`.
  OpenRouter chooses an available free model for this router; model
  availability, tool support, and rate limits can vary.
- `PAYPAL_API_BASE_URL` — PayPal API base URL; defaults to the Sandbox host for
  local testing. Use `https://api-m.paypal.com` only for production.
- `PAYPAL_CLIENT_ID` and `PAYPAL_SECRET_KEY` — backend-only PayPal REST app
  credentials. Never expose them to the frontend or log them.
- `APP_ENV=production` disables the generated OpenAPI and Swagger endpoints.

In development, OpenAPI is available at `/api/v1/openapi.json` and Swagger UI
at `/api/v1/docs`.

## Supabase schema

Review and run, in order,
[`src/supabase/migrations/0001_core_schema.sql`](src/supabase/migrations/0001_core_schema.sql)
and
[`src/supabase/migrations/0002_strands_agent_queue.sql`](src/supabase/migrations/0002_strands_agent_queue.sql)
manually in the Supabase SQL Editor. Neither has been applied by this project.
Test them against a non-production Supabase project before production use.

Migrations are append-only once shared or run. Never edit a migration that
someone may have applied; create the next ordered SQL file in
`src/supabase/migrations/` for every subsequent schema change, with a short
description of the change and its reason.

## Current integration limits

- Owner-assistant messages are atomically persisted with durable agent runs.
  When enabled, a lifespan-managed worker claims jobs with database leases and
  runs Strands outside the request path, so other API requests continue while
  the model responds. The model receives one read-only tool for the current
  business's active, agent-enabled products; it cannot place orders, contact
  customers, or change business data. A `202` response means queued, not
  answered; clients can poll the returned agent run ID for its status.
- Strands uses OpenRouter through its OpenAI-compatible provider, with the
  `openrouter/free` model router by default. No MCP server is configured in
  this project, and the current scoped catalog tool does not require one. Do
  not attach a third-party MCP server without an explicit trust and permission
  review.
- Customer replies are durably queued, but their provider-delivery worker is
  not implemented. A `202` response means queued, not delivered.
- PayPal webhook signature verification is implemented, but PayPal checkout
  creation, capture/reconciliation, and payment-state transitions are not yet
  implemented; approval gating is available and the direct checkout path
  returns `503`.
- Telegram credentials are stored encrypted; connection testing calls `getMe`
  and registers `setWebhook`. Inbound normalization and outbound delivery are
  implemented for text/caption messages; the Business Agent replies through the
  originating Telegram chat. Telegram photo messages are recorded as customer
  attachments for the conversation.
- WooCommerce and Shopify credentials can be tested and their products can be
  imported into the tenant's catalog. Each imported product is scoped by
  `business_id` and provider source.
- OAuth authorization/callback, provider connection tests/sync, and WhatsApp
  webhook are marked planned and return an explicit unavailable response.
- `POST /api/v1/businesses/{business_id}/agent/test` invokes OpenRouter; free
  model availability and rate limits apply. It is restricted to owners and
  admins.
- Configure all HTTPS origins and secrets before enabling the related
  integration. Do not use a service-role key in user-scoped routes.