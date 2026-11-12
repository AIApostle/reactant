# AgentCard setup and PayPal guide

AgentCard is Reactant's hosted customer checkout for purchases started by a
Business Agent. The agent submits catalog product IDs and quantities; the
backend loads prices from the current catalog, validates the order and stock,
reserves inventory, and stores an immutable checkout snapshot. The customer
reviews the items and total and explicitly authorizes payment before Reactant
creates a PayPal order.

Reactant never stores card details or treats a browser redirect as proof of
payment. The backend verifies a completed capture before updating the order.
Webhook events are signature-verified and deduplicated.

PayPal Checkout uses Reactant's partner REST app to route buyer payments to
the business's PayPal account. Business owners enter only their PayPal account
email; the app client ID, secret, and BN attribution code remain backend-only.
With PayPal's **Onboard after payment** capability, the first payment may
remain pending until the seller completes onboarding. PayPal requires the
seller to have a business account and returns the buyer's payment if onboarding
isn't completed within 30 days.

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
APP_ENV=production
ALLOWED_WEB_ORIGINS=https://getreactant.vercel.app
PUBLIC_API_BASE_URL=https://reactant.onrender.com
PUBLIC_FRONTEND_URL=https://getreactant.vercel.app
PAYPAL_API_BASE_URL=https://api-m.sandbox.paypal.com
PAYPAL_RECEIVING_COUNTRIES=US,NG
PAYPAL_CLIENT_ID=<reactant-sandbox-partner-app-client-id>
PAYPAL_SECRET_KEY=<reactant-sandbox-partner-app-secret>
PAYPAL_PARTNER_ATTRIBUTION_ID=<reactant-bn-code>
PAYPAL_ONBOARDING_AFTER_PAYMENT_ENABLED=true
AGENTCARD_ENABLED=false
STRANDS_AGENT_ENABLED=true
GEMINI_API_KEY=<server-only-google-ai-studio-key>
```

Generate `CREDENTIALS_ENCRYPTION_KEY` with:

```sh
cd backend
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Keep the Fernet key stable: changing it makes existing encrypted integration
credentials unreadable. `SUPABASE_SECRET_KEY` enables the backend's scoped
service-role operations and AgentCard worker; never put it in Vercel. The
Strands worker and Gemini API key are needed for the agent to
create checkouts from Telegram or other supported customer conversations. The
customer checkout itself uses public, token-scoped API routes.

`PAYPAL_RECEIVING_COUNTRIES` is a comma-separated country allowlist. The
business profile country must be included. Nigeria (`NG`) is allowed only for
Sandbox tests when explicitly included in this list; Live checkout always
blocks it. Set `AGENTCARD_ENABLED=true` or
`AGENTCARD_ENABLED=True` in Render to enable AgentCard; both spellings are
accepted. Set `PAYPAL_ONBOARDING_AFTER_PAYMENT_ENABLED=true` only after PayPal has
enabled **Onboard after payment** for Reactant's REST app. This code flag
doesn't change the PayPal Developer Dashboard setting. For Sandbox, use the
Sandbox app credentials, BN code, and Sandbox API URL; for production, use the
Live app credentials, BN code, and Live API URL.

Strands `Agent` orchestrates the conversation and tool calls. All inference uses
Google's Gemini API, including image requests. The default model is
`gemini-3.6-flash`; `GEMINI_MODEL_ID` and `GEMINI_VISION_MODEL_ID` can override
the text and vision models. Configure `GEMINI_API_KEY` only on the backend and
never expose it to the frontend.

### Vercel frontend environment

Configure the frontend to use the same Supabase project and deployed API:

```dotenv
VITE_API_BASE_URL=https://reactant.onrender.com/api/v1
VITE_SUPABASE_URL=https://<project-ref>.supabase.co
VITE_SUPABASE_ANON_KEY=<public-publishable-or-anon-key>
```

Only the Supabase public key belongs in Vercel. AgentCard checkout pages are
served at `https://getreactant.vercel.app/checkout/<token>`.

### PayPal seller payments and after-payment onboarding

1. Confirm Reactant's PayPal account is approved for Multiparty and that
   **Onboard after payment** is enabled on the REST app in PayPal's Developer
   Dashboard. The application cannot enable this PayPal-side capability.
2. Keep the REST app client ID, secret, and BN code in Render only. Set
   `PAYPAL_API_BASE_URL=https://api-m.sandbox.paypal.com`,
   `PAYPAL_ONBOARDING_AFTER_PAYMENT_ENABLED=true`, and
   `AGENTCARD_ENABLED=true` for Sandbox. Use only Sandbox app credentials and
   Sandbox buyer and seller accounts for testing.
3. In Reactant's Integrations page, enter the seller's PayPal business account
   email and choose **Connect PayPal account**. The first customer payment is
   routed to that seller's email; PayPal sends the seller an onboarding email.
   The seller must finish onboarding within 30 days. Until then, payment status
   can remain pending and refunds are unavailable.
4. In the corresponding Sandbox REST app, create a webhook for
   `https://reactant.onrender.com/webhooks/paypal/<integration-id>`. Subscribe to
   `MERCHANT.ONBOARDING.COMPLETED`, `MERCHANT.PARTNER-CONSENT.REVOKED`,
   `CHECKOUT.ORDER.APPROVED`, `PAYMENT.CAPTURE.COMPLETED`,
   `PAYMENT.CAPTURE.PENDING`, `PAYMENT.CAPTURE.DENIED`,
   `PAYMENT.CAPTURE.REFUNDED`, and
   `CHECKOUT.PAYMENT-APPROVAL.REVERSED`. Store the returned webhook ID in the
   Render backend's `PAYPAL_WEBHOOK_IDS` JSON object, keyed by the integration
   ID in that URL. Webhook IDs are not entered or displayed in the frontend.
5. Test with a Sandbox buyer and a Sandbox seller business account. Funds are
   routed to the business seller, not Reactant. A seller who doesn't complete
   onboarding within 30 days has the pending payment returned to the buyer.

## Configure the test business and agent

1. Sign in as an owner/admin and select a business whose country is in
   `PAYPAL_RECEIVING_COUNTRIES`.
2. Add an active catalog product with a price, currency, and stock quantity.
   Enable **Visible to agent** for that product.
3. Connect Telegram (or another supported customer channel), then connect the
   business PayPal seller account as described above.
4. In **Business agent**, enable the agent and **Prepare AgentCard checkout**.
   This permission enables both cart validation and secure checkout links. Save
   the settings.
5. Keep order approvals configured according to the test you want to run. If
   approval is required, an owner/admin must approve the request before
   checkout can proceed.
6. Confirm Integrations shows the PayPal connection and that the matching
   webhook ID is configured in the Render backend environment. Never use Live
   PayPal credentials for Sandbox testing.

## Run a complete Sandbox purchase

1. To test payment without calling the AI agent, an owner/admin can request a
   temporary Sandbox checkout directly:

   ```sh
   curl --request POST \
     --url "https://reactant.onrender.com/api/v1/businesses/<BUSINESS_ID>/agentcard/test-checkout" \
     --header "Authorization: Bearer <OWNER_ACCESS_TOKEN>" \
     --header "Content-Type: application/json" \
     --header "Idempotency-Key: sandbox-checkout-001" \
     --data '{
       "customer_name": "Sandbox payment test",
       "items": [{"product_id": "<CATALOG_PRODUCT_UUID>", "quantity": 1}]
     }'
   ```

   Use an active catalog product ID. The response includes a `checkout_url`;
   open it in a browser and complete checkout with a Sandbox buyer account.
   This endpoint is owner/admin-only, creates a test conversation record, and
   works only when the backend PayPal API URL is the Sandbox URL. Use a new
   `Idempotency-Key` for each separate purchase attempt.
2. To exercise the agent itself, from a separate customer Telegram account,
   ask about the test product.
3. Express clear purchase intent and confirm the exact item and quantity when
   the agent asks. The agent must use the backend checkout tool; it must not
   invent or calculate a price itself.
4. Open the secure checkout URL that the agent sends. Check the merchant,
   items, quantities, currency, and total.
5. Explicitly accept the displayed checkout consent. Continue to PayPal and
   sign in with the Sandbox personal buyer account to approve the payment.
6. Return to the Reactant checkout page. The backend retrieves the PayPal
   order and verifies the captured amount/currency before showing payment as
   confirmed. A return redirect by itself is not confirmation.
7. Confirm the business order is paid and the receipt worker generates a
   receipt. For Telegram, verify receipt delivery in the customer conversation.

An unpaid checkout expires after 30 minutes. Use the same checkout link while
its status is pending; do not start a second payment when the page says payment
is being checked. The checkout status endpoint polls pending/reconciliation
states.

## What to verify

- The PayPal integration reports **Connected** after its credential test.
- The backend `PAYPAL_WEBHOOK_IDS` value includes the PayPal integration ID and
  matching webhook ID.
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

- **Agent does not offer checkout:** check that PayPal Multiparty access and
  the **Onboard after payment** capability are enabled, and check
  `PAYPAL_ONBOARDING_AFTER_PAYMENT_ENABLED` and `AGENTCARD_ENABLED`,
  `STRANDS_AGENT_ENABLED`, `GEMINI_API_KEY`, agent permissions, enabled
  product, catalog stock, and business country.
- **PayPal partner app is not configured:** check Render's backend-only
  `PAYPAL_CLIENT_ID`, `PAYPAL_SECRET_KEY`, `PAYPAL_PARTNER_ATTRIBUTION_ID`,
  and API URL. Never ask a business to enter these app credentials.
- **Webhook verification is not configured:** confirm `PAYPAL_WEBHOOK_IDS` maps
  the PayPal integration ID to the webhook ID registered for that exact URL and
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
