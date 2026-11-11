# AgentCard setup and Sandbox test guide

AgentCard is Reactant's hosted customer checkout for purchases started by a
Business Agent. The agent submits catalog product IDs and quantities; the
backend loads prices from the current catalog, validates the order and stock,
reserves inventory, and stores an immutable checkout snapshot. The customer
reviews the items and total and explicitly authorizes payment before Reactant
creates a PayPal order.

PayPal credentials belong to the business and are encrypted in Supabase.
Reactant never stores card details, holds merchant funds, or treats a browser
redirect as proof of payment. The backend verifies a completed capture with
PayPal before updating the order. Webhook events are signature-verified and
deduplicated. A background worker expires unpaid checkouts, reconciles
unfinished payments/refunds, and generates receipts.

## What must be configured

### Supabase

Use the same Supabase project in Vercel and Render. Apply migrations in order,
including:

- `backend/src/supabase/migrations/0001_core_schema.sql`
- `backend/src/supabase/migrations/0002_strands_agent_queue.sql`
- `backend/src/supabase/migrations/0003_agentcard_transactions.sql`
- Migrations `0004` through `0008`

Migration 0003 creates the transaction, checkout, payment, webhook, refund,
and receipt tables, their access policies and service-role functions, and the
private `agentcard-receipts` Storage bucket. Do not enable payments against a
database that has not applied it.

### Render backend environment

Set these in the Render service's Environment settings; local `.env` values do
not deploy:

```dotenv
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_PERISHABLE_KEY=<server-compatible-publishable-or-anon-key>
SUPABASE_SECRET_KEY=<server-only-secret-key>
CREDENTIALS_ENCRYPTION_KEY=<fernet-key>
ALLOWED_WEB_ORIGINS=https://getreactant.vercel.app
PUBLIC_API_BASE_URL=https://reactant.onrender.com
PUBLIC_FRONTEND_URL=https://getreactant.vercel.app
PAYPAL_API_BASE_URL=https://api-m.sandbox.paypal.com
PAYPAL_RECEIVING_COUNTRIES=US
AGENTCARD_ENABLED=false
STRANDS_AGENT_ENABLED=true
OPENROUTER_API_KEY=<server-only-openrouter-key>
```

Generate `CREDENTIALS_ENCRYPTION_KEY` with:

```sh
cd backend
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Keep the Fernet key stable: changing it makes existing encrypted integration
credentials unreadable. `SUPABASE_SECRET_KEY` enables the backend's scoped
service-role operations and AgentCard worker; never put it in Vercel. The
Strands worker and OpenRouter key are needed for the agent to create checkouts
from Telegram or other supported customer conversations. The customer
checkout itself uses public, token-scoped API routes.

`PAYPAL_RECEIVING_COUNTRIES` is a comma-separated country allowlist. The
business profile country must be included; Nigeria (`NG`) is explicitly
blocked by the current eligibility check. Keep `AGENTCARD_ENABLED=false`
until the Sandbox test succeeds.

### Vercel frontend environment

Configure the frontend to use the same Supabase project and deployed API:

```dotenv
VITE_API_BASE_URL=https://reactant.onrender.com/api/v1
VITE_SUPABASE_URL=https://<project-ref>.supabase.co
VITE_SUPABASE_ANON_KEY=<public-publishable-or-anon-key>
```

Only the Supabase public key belongs in Vercel. AgentCard checkout pages are
served at `https://getreactant.vercel.app/checkout/<token>`.

### PayPal Sandbox

1. In the PayPal Developer Dashboard, create a Sandbox business account for
   the merchant and a Sandbox personal account for the buyer.
2. Create a REST app under the Sandbox business account. Keep its Sandbox
   client ID and secret available to enter in Reactant.
3. In Reactant, open the test business's **Integrations** page, connect
   **PayPal** with the Sandbox client ID and secret, then use **Test**. The
   test should set the integration to Connected.
4. On the PayPal integration card, choose **Webhook setup** and copy the exact
   webhook URL Reactant displays. In the same Sandbox REST app, create a
   webhook pointing to that URL. Subscribe to:
   - `CHECKOUT.ORDER.APPROVED`
   - `PAYMENT.CAPTURE.COMPLETED`
   - `PAYMENT.CAPTURE.PENDING`
   - `PAYMENT.CAPTURE.DENIED`
   - `PAYMENT.CAPTURE.REFUNDED`
   - `CHECKOUT.PAYMENT-APPROVAL.REVERSED`
5. Copy the webhook ID from PayPal back into Reactant's **Webhook setup**
   panel and save it. Reactant stores it encrypted with the business's PayPal
   credentials; it is not returned by the API.
6. Confirm `PAYPAL_API_BASE_URL` is still the Sandbox host. Live credentials
   must not be used for this test.

The two-step process is intentional: PayPal requires the webhook URL, which
contains the integration ID generated when the credentials are first saved.
The webhook ID is saved only after PayPal creates that webhook.

## Configure the test business and agent

1. Sign in as an owner/admin and select a business whose country is in
   `PAYPAL_RECEIVING_COUNTRIES`.
2. Add an active catalog product with a price, currency, and stock quantity.
   Enable **Visible to agent** for that product.
3. Connect and test Telegram (or another supported customer channel), and
   connect/test the business's PayPal Sandbox app and configure its webhook.
4. In **Business agent**, enable the agent, **Build carts and prepare orders**,
   and **Create PayPal checkout links**. Save the settings.
5. Keep order approvals configured according to the test you want to run. If
   approval is required, an owner/admin must approve the request before
   checkout can proceed.
6. Set `AGENTCARD_ENABLED=true` in Render and redeploy. Check Render logs for
   worker startup errors before sending a customer message.

## Run a complete Sandbox purchase

1. From a separate customer Telegram account, ask about the test product.
2. Express clear purchase intent and confirm the exact item and quantity when
   the agent asks. The agent must use the backend checkout tool; it must not
   invent or calculate a price itself.
3. Open the secure checkout URL that the agent sends. Check the merchant,
   items, quantities, currency, and total.
4. Explicitly accept the displayed checkout consent. Continue to PayPal and
   sign in with the Sandbox personal buyer account to approve the payment.
5. Return to the Reactant checkout page. The backend retrieves the PayPal
   order and verifies the captured amount/currency before showing payment as
   confirmed. A return redirect by itself is not confirmation.
6. Confirm the business order is paid and the receipt worker generates a
   receipt. For Telegram, verify receipt delivery in the customer conversation.

An unpaid checkout expires after 30 minutes. Use the same checkout link while
its status is pending; do not start a second payment when the page says payment
is being checked. The checkout status endpoint polls pending/reconciliation
states.

## What to verify

- The PayPal integration reports **Connected** after its credential test.
- The webhook setup panel reports the webhook ID saved.
- The customer checkout displays a server-calculated immutable order snapshot
  and requires explicit consent.
- `PAYMENT.CAPTURE.COMPLETED` has a valid PayPal signature and its amount,
  currency, and transaction reference match before the order becomes paid.
- Replayed webhook events do not duplicate payment/order/receipt effects.
- Receipts and refunds reach their verified terminal status in the transaction
  ledger.

For refunds, an owner/admin uses
`POST /api/v1/businesses/{business_id}/agentcard/transactions/{transaction_id}/refunds`
with `amount_minor`, an optional reason, and a stable `Idempotency-Key`. Use
minor currency units (for example, `1250` means `$12.50`); retry an uncertain
request with the same idempotency key.

## Troubleshooting

- **Agent does not offer checkout:** check `AGENTCARD_ENABLED`,
  `STRANDS_AGENT_ENABLED`, `OPENROUTER_API_KEY`, agent permissions, enabled
  product, catalog stock, business country, and that PayPal is connected.
- **Checkout says PayPal is not ready:** test the business PayPal credentials
  again. Ensure the integration uses Sandbox credentials and
  `PAYPAL_API_BASE_URL=https://api-m.sandbox.paypal.com`.
- **Webhook verification is not configured:** configure the webhook ID in the
  PayPal integration card and verify the webhook belongs to the same Sandbox
  REST app.
- **Payment remains pending or reconciliation:** do not retry payment with a
  new checkout. Check PayPal Sandbox activity and Render logs; the backend
  worker also reconciles unfinished payment attempts.
- **No receipt:** confirm `SUPABASE_SECRET_KEY` is set and migration 0003's
  `agentcard-receipts` bucket and receipt functions exist, then inspect Render
  worker logs.

Never enable live payments until PayPal confirms merchant eligibility and any
required partner approval, and production monitoring and incident procedures
are in place. AgentCard's current implementation is not a claim of AP2
conformance or PayPal platform/partner approval.
