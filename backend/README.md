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
  operations including public website chat and private memory. Never expose it
  to the frontend.
- `MEMWAL_DELEGATE_KEY` and `MEMWAL_ACCOUNT_ID` — backend-only Walrus Memory
  credentials. Optionally set `MEMWAL_SERVER_URL` to use a custom relayer; the
  SDK uses its production relayer by default. Memory is isolated by business
  and customer namespace. The Python SDK derives the public key from the
  delegate key, so `MEMWAL_PUBLIC_KEY` is not required.
- `CREDENTIALS_ENCRYPTION_KEY` — Fernet key required to store integration
  credentials. Generate one with
  `uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
- `ALLOWED_WEB_ORIGINS` — comma-separated exact browser origins for the Reactant
  app and authenticated WebSocket origin checks. Website widget origins are
  registered per business and checked by the public widget routes.
- `PUBLIC_API_BASE_URL` — public HTTPS backend URL used for provider webhooks,
  such as `https://reactant.onrender.com`.
- `INVITATION_DELIVERY_URL` and `INVITATION_DELIVERY_TOKEN` — HTTPS invitation
  delivery webhook.
- `INTERNAL_SERVICE_TOKEN` — authentication for trusted internal agent calls.
- `STRANDS_AGENT_ENABLED=true` — opt in to the Strands background worker,
  owner-assistant runtime, and website chat agent. Requires
  `SUPABASE_SECRET_KEY` and
  `OPENROUTER_API_KEY`. Keep disabled until these credentials and the Supabase
  migration are configured.
- `OPENROUTER_API_KEY` — backend-only OpenRouter API key used by Strands'
  OpenAI-compatible provider. Do not expose it to the frontend.
- `openrouter_api_key` is accepted as an equivalent environment variable name.
- `OPENROUTER_MODEL_ID` — optional model ID; defaults to `openrouter/free`.
  OpenRouter chooses an available free model for this router; model
  availability, tool support, and rate limits can vary.
- `OPENROUTER_VISION_MODEL_ID` — optional vision-capable model for customer
  image messages; defaults to `google/gemini-2.5-flash`. Vision requests may
  incur provider charges and require model access.
- `PAYPAL_API_BASE_URL` — PayPal API base URL; defaults to the Sandbox host for
  local testing. Use `https://api-m.paypal.com` only for production.
- `PUBLIC_FRONTEND_URL` — HTTPS frontend origin used for customer checkout and
  for hosting the `reactant-chat.js` website widget installer.
- `AGENTCARD_ENABLED` — deployment-wide opt-in for agent-originated checkout;
  defaults to `false`.
- `PAYPAL_RECEIVING_COUNTRIES` — comma-separated business country allowlist;
  defaults to `US`.
- `PAYPAL_CLIENT_ID` and `PAYPAL_SECRET_KEY` are legacy backend settings and
  are not used by AgentCard. AgentCard uses the encrypted PayPal credentials
  connected by each business; it never falls back to deployment credentials.
- The OpenAPI definition is available at `/api/v1/openapi.json` in every
  environment so APIMatic can import the current API contract. Swagger UI at
  `/api/v1/docs` remains disabled in production.

In development, Swagger UI is available at `/api/v1/docs`.

## Supabase schema

Review and run, in order,
[`src/supabase/migrations/0001_core_schema.sql`](src/supabase/migrations/0001_core_schema.sql)
and
[`src/supabase/migrations/0002_strands_agent_queue.sql`](src/supabase/migrations/0002_strands_agent_queue.sql),
then
[`src/supabase/migrations/0003_agentcard_transactions.sql`](src/supabase/migrations/0003_agentcard_transactions.sql)
and
[`src/supabase/migrations/0004_chat_widgets_and_memory.sql`](src/supabase/migrations/0004_chat_widgets_and_memory.sql)
and
[`src/supabase/migrations/0005_customer_chat_images.sql`](src/supabase/migrations/0005_customer_chat_images.sql)
and
[`src/supabase/migrations/0006_integration_allowed_origins.sql`](src/supabase/migrations/0006_integration_allowed_origins.sql)
manually in the Supabase SQL Editor. The application does not apply migrations
automatically. Test them against a non-production Supabase project before
production use.

Migrations are append-only once shared or run. Never edit a migration that
someone may have applied; create the next ordered SQL file in
`src/supabase/migrations/` for every subsequent schema change, with a short
description of the change and its reason.

The Render service's local `.env` is not deployed. Set backend-only variables
in the Render service environment as well. If the Integrations page returns
503 and backend logs report PostgreSQL code `42703` for
`integrations.allowed_origin`, apply migration `0006` in the hosted Supabase
project before retrying.

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
- AgentCard supports PayPal Sandbox checkout, customer consent, server-verified
  capture, signed PayPal webhooks, idempotent partial/full refunds, reconciliation
  of pending payments, and a durable PDF receipt worker. Receipt delivery is
  currently available for Telegram conversations; other channels can retrieve
  an expiring signed receipt URL after generation.
- AgentCard is disabled until `AGENTCARD_ENABLED=true`, the merchant's own
  PayPal integration is connected and tested, the business country is
  allowlisted, and the agent's order/PayPal permissions are enabled. These
  controls do not establish PayPal live eligibility or AP2 compliance.
- Telegram credentials are stored encrypted; connection testing calls `getMe`
  and registers `setWebhook`. Inbound normalization and outbound delivery are
  implemented for text/caption messages; the Business Agent replies through the
  originating Telegram chat. Telegram photos and image documents are validated,
  normalized, stored in a private bucket, and sent as image inputs to a
  vision-capable OpenRouter model. Website chat accepts image data URLs through
  its authenticated widget-session endpoint. WhatsApp remains unimplemented.
- WooCommerce and Shopify credentials can be tested and their products can be
  imported into the tenant's catalog. Each imported product is scoped by
  `business_id` and provider source.
- WooCommerce may also be tested through its official MCP endpoint by supplying
  `mcp_endpoint` with the store URL and a least-privilege API key. The endpoint
  is restricted to the store host or `public-api.wordpress.com`; arbitrary MCP
  servers are not accepted. The existing REST catalog sync remains the source
  of imported products.
- Shopify uses the authorization-code OAuth flow. Configure
  `SHOPIFY_CLIENT_ID`, `SHOPIFY_CLIENT_SECRET`, `SHOPIFY_SCOPES`, and the exact
  callback URL `/api/v1/integrations/callback/shopify` in both Shopify and
  Render. Owners enter only their `*.myshopify.com` domain; the access token is
  exchanged and encrypted by the backend.
- Website chat can be installed from Integrations using the generated script.
  Register each exact HTTPS origin first; localhost is accepted for local
  testing. Widget HTTP requests and WebSockets are origin-bound and use signed
  short-lived session tokens. The reusable app API uses the same session and
  message endpoints under `/api/v1/public/widgets/`; do not embed business
  credentials in client apps.
  For local testing, use the local Vite script and API explicitly:
  `<script async src="http://localhost:5173/reactant-chat.js" data-business-id="BUSINESS_UUID" data-api-url="http://localhost:8000/api/v1"></script>`.
- Website chat accepts up to three customer JPEG, PNG, or WebP images per
  message. It stores private normalized images in Supabase Storage; apply
  migrations `0004` and `0005` before enabling image messages.
- Walrus Memory credentials are configured only on the backend and are not
  stored as per-business integrations.
  Owner memories use a business-specific namespace; customer memory uses a
  business- and customer-specific namespace and is available only after
  explicit customer opt-in. Avoid storing secrets or sensitive personal data.
- OAuth authorization/callback, provider connection tests/sync, and WhatsApp
  webhook are marked planned and return an explicit unavailable response.
- `POST /api/v1/businesses/{business_id}/agent/test` invokes OpenRouter; free
  model availability and rate limits apply. It is restricted to owners and
  admins.
- Configure all HTTPS origins and secrets before enabling the related
  integration. Do not use a service-role key in user-scoped routes.
- AgentCard uses the merchant's encrypted PayPal app credentials, USD checkout,
  a 30-minute checkout expiry, backend-calculated prices, and owner/admin-only
  refunds. PayPal Sandbox success and external platform approval must be
  verified before live use.
- `CREDENTIALS_ENCRYPTION_KEY` is required before creating an integration. Set
  the same Fernet key in local development and Render; changing it makes
  previously stored integration credentials unreadable.