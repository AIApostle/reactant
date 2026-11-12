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
  `SUPABASE_SECRET_KEY` and `GEMINI_API_KEY`. Keep
  disabled until these credentials and the Supabase
  migration are configured.
- `GEMINI_API_KEY` — backend-only Google AI Studio key. Strands uses Gemini for
  text and vision inference, with `gemini-3.6-flash` as the default model.
  `GEMINI_MODEL_ID` and `GEMINI_VISION_MODEL_ID` can override the model IDs.
  Never expose the key to the frontend.
- `PAYPAL_API_BASE_URL` — PayPal API base URL; defaults to the Sandbox host for
  local testing. Use `https://api-m.paypal.com` only for production.
- `PAYPAL_WEBHOOK_IDS` — backend-only JSON object mapping each PayPal integration
  UUID in the webhook URL to its PayPal webhook ID. Do not configure this in the
  frontend or store it with seller account credentials.
- `PUBLIC_FRONTEND_URL` — HTTPS frontend origin used for customer checkout and
  for hosting the `reactant-chat.js` website widget installer. Defaults to
  `https://getreactant.vercel.app`; set `http://localhost:5173` for local
  checkout testing. Production refuses localhost checkout links.
- `APP_ENV=production` — enables production URL validation for customer
  checkout links.
- `AGENTCARD_ENABLED` — deployment-wide opt-in for agent-originated checkout;
  defaults to `false`; both `true` and `True` are accepted.
- `PAYPAL_ONBOARDING_AFTER_PAYMENT_ENABLED` — explicit opt-in after PayPal has
  enabled the **Onboard after payment** capability for Reactant's partner REST
  app. The code flag does not enable the capability in PayPal's dashboard.
- `PAYPAL_PARTNER_ATTRIBUTION_ID` — Reactant's BN attribution code, backend-only.
  Existing local environments may keep using `PAYPAL_BN_CODE`.
- `PAYPAL_RECEIVING_COUNTRIES` — comma-separated business country allowlist;
  defaults to `US,NG`. Nigeria is accepted only with the PayPal Sandbox API;
  the backend blocks it when PayPal Live is configured.
- `PAYPAL_CLIENT_ID` and `PAYPAL_SECRET_KEY` are backend-only platform app
  credentials. Businesses enter only their PayPal account email, never their
  app credentials. Use the Sandbox app credentials and Sandbox seller/buyer
  accounts for testing.
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
- Strands uses Google's Gemini API for text and vision inference. No alternate
  provider or fallback is configured.
  No MCP server is configured in this project, and the current scoped catalog
  tool does not require one. Do not attach a third-party MCP server without an
  explicit trust and permission review.
- Customer replies are durably queued, but their provider-delivery worker is
  not implemented. A `202` response means queued, not delivered.
- The AgentCard checkout engine supports PayPal seller-email checkout with
  after-payment onboarding, customer consent, server-verified capture, signed
  webhooks, refunds, reconciliation, and receipts. Customers can choose a
  PayPal account or ask PayPal to show guest card checkout when eligible.
  This onboarding mode does not support Expanded Checkout's inline card fields.
  The Business Agent can read current transaction statuses for the owner.
  Seller onboarding and payment capabilities still require PayPal approval and
  dashboard setup.
- Strands `Agent` remains the orchestration runtime: it manages the conversation
  loop and invokes registered tools. Gemini supplies model inference;
  catalog lookup, total calculation, and AgentCard transaction creation remain
  backend tools with server-side validation.
- AgentCard is disabled until `AGENTCARD_ENABLED=true`, PayPal seller
  onboarding is approved and implemented, the business country is
  allowlisted, and the agent's order/PayPal permissions are enabled. These
  controls do not establish PayPal live eligibility or AP2 compliance.
- Telegram credentials are stored encrypted; connection testing calls `getMe`
  and registers `setWebhook`. Inbound normalization and outbound delivery are
  implemented for text/caption messages; the Business Agent replies through the
  originating Telegram chat. Telegram photos and image documents are validated,
  normalized, stored in a private bucket, and sent as image inputs to a
  vision-capable Gemini model. Website chat accepts image data URLs through
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
- `POST /api/v1/businesses/{business_id}/agent/test` invokes Gemini. Model
  availability and rate limits apply. It is restricted to owners and
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
