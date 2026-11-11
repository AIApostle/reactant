# Reactant MVP Setup

This setup follows the product workflow in [`prd.md`](./prd.md):

1. A business creates an internal catalog.
2. The business connects a Telegram bot.
3. The Business Agent answers from approved catalog data.
4. After clear customer purchase intent, the Business Agent prepares a
   server-priced AgentCard checkout from active catalog items.
5. The customer reviews the immutable order and authorizes payment on the
   public checkout page, then pays through the merchant's PayPal account.
6. The backend verifies PayPal capture details before confirming payment,
   issuing a receipt, and updating the order.

Reactant never receives or stores money. Each business connects its own PayPal
merchant application, so PayPal sends the payment to that business's PayPal
account. Reactant does not hold merchant funds. Refunds are explicit
owner/admin actions and are verified with PayPal before the order ledger is
updated.

For the detailed AgentCard environment checklist, PayPal webhook setup, and
end-to-end Sandbox procedure, see [`AGENTCARD_SETUP.md`](./AGENTCARD_SETUP.md).

## What is already in the repository

- Supabase Auth and business tenancy.
- Manual product catalog and private product image uploads.
- Encrypted integration credential storage.
- Telegram inbound/outbound messaging and verified Telegram webhooks.
- PayPal sandbox order creation, capture verification, webhook verification,
  payment reconciliation, and idempotent refund recording.
- Public AgentCard checkout pages with immutable totals and explicit customer
  consent.
- Private PDF receipt generation and Telegram delivery, plus expiring signed
  receipt links.
- Strict tenant authorization and idempotency requirements.

Sandbox support is implemented but is disabled by default. It is not a
production financial-services certification: AP2 conformance, PayPal partner
approval, live-country eligibility, and production operational controls must
be verified separately before enabling live transactions.

## 1. Prepare the hosted environment

For the hosted deployment, set these values in the deployment dashboards.
The `.env.example` files are templates only; do not rely on local `.env` files
for Vercel or Render.

### Render backend environment

```dotenv
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_PERISHABLE_KEY=<server-compatible-supabase-key>
SUPABASE_SECRET_KEY=<server-only-secret-key>
CREDENTIALS_ENCRYPTION_KEY=<fernet-key>
ALLOWED_WEB_ORIGINS=https://getreactant.vercel.app
PAYPAL_API_BASE_URL=https://api-m.sandbox.paypal.com
PUBLIC_API_BASE_URL=https://reactant.onrender.com
PUBLIC_FRONTEND_URL=https://getreactant.vercel.app
AGENTCARD_ENABLED=false
PAYPAL_RECEIVING_COUNTRIES=US
OPENROUTER_VISION_MODEL_ID=google/gemini-2.5-flash
```

The Render service's public API origin is:

```text
https://reactant.onrender.com
```

### Vercel frontend environment

```dotenv
VITE_API_BASE_URL=https://reactant.onrender.com/api/v1
VITE_SUPABASE_URL=https://<project-ref>.supabase.co
VITE_SUPABASE_ANON_KEY=<public-publishable-or-anon-key>
```

`ALLOWED_WEB_ORIGINS` must exactly match the browser origin, including
`https://` and excluding a trailing slash. Add preview deployment origins
separately only when they are intentionally allowed.

`PUBLIC_API_BASE_URL` is used when constructing provider webhook URLs.
`PUBLIC_FRONTEND_URL` is used for customer checkout and PayPal return URLs.
Both must be exact public HTTPS origins in the hosted deployment. The backend
must be reachable before Telegram or PayPal can deliver webhooks.

Generate the encryption key with:

```bash
cd backend
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Never put `SUPABASE_SECRET_KEY`, PayPal client secrets, or Telegram bot tokens
in the frontend environment or commit them to Git. The PayPal values above are
backend-only and are loaded from `backend/.env`.

## 2. Prepare Supabase

1. Create or select the Supabase project used by both frontend and backend.
2. Apply `backend/src/supabase/migrations/0001_core_schema.sql`.
3. Apply `backend/src/supabase/migrations/0002_strands_agent_queue.sql` if it
   has not already been applied.
4. Apply `backend/src/supabase/migrations/0003_agentcard_transactions.sql`.
5. Apply `backend/src/supabase/migrations/0004_chat_widgets_and_memory.sql`
   if it has not already been applied.
6. Apply `backend/src/supabase/migrations/0005_customer_chat_images.sql`.
7. Enable email/password Auth.
8. For local testing, keep email confirmation disabled or use confirmed test
   users.
9. Confirm the private `product-media`, `agentcard-receipts`, and
   `customer-chat-media` buckets exist; migrations 0003 and 0005 create the
   AgentCard and customer image buckets.

The frontend must use only the public Supabase URL and publishable/anon key.

## 3. Prepare the first catalog

For the first test business, prepare at least:

- Product name.
- Description containing the facts the agent may state.
- Category.
- Price and currency.
- Optional stock quantity.
- One JPEG, PNG, or WebP product image under 5 MB.
- Whether the agent may use the product and share its image.

Create the product from the Catalog page after signing in. The catalog is
internal agent context; it is not a public storefront. An empty stock quantity
means stock is unknown, not that the product is available.

## 4. Prepare Telegram

1. Open Telegram and message `@BotFather`.
2. Run `/newbot`.
3. Choose a bot name and username.
4. Save the bot token in a password manager; do not paste it into GitHub,
   frontend environment files, screenshots, or support messages.
5. Ensure the backend has a public HTTPS URL. Telegram cannot call
   `localhost`.
6. The webhook URL will be:

   ```text
   https://<public-backend-host>/webhooks/telegram/<integration_id>
   ```

7. Generate a high-entropy webhook secret and keep it available for the
   integration configuration.
8. Connect the bot in the Integrations page as a workspace owner/admin. The
   backend validates the token and configures the public webhook.
9. Verify the bot with a test message from a second Telegram account.
10. Send the bot a JPEG, PNG, or WebP product photo with a question and verify
    the agent answers from visible image contents.

Required testing outcomes:

- Telegram `getMe` validates the token.
- Telegram `setWebhook` succeeds with the public HTTPS webhook URL.
- Incoming updates are signature/secret checked and deduplicated.
- The conversation is associated with the correct business.
- Outbound replies and payment receipts are sent by the backend using the
  stored bot token.

## 5. Prepare PayPal Sandbox

Use the PayPal Developer Dashboard, not a personal password:

1. Create a PayPal Sandbox business account for the test business.
2. Create a Sandbox REST app under that business account.
3. Save the Sandbox client ID and client secret securely.
4. Set `PAYPAL_API_BASE_URL=https://api-m.sandbox.paypal.com`.
5. Use a Sandbox personal account as the customer and the Sandbox business
   account as the merchant.

Connect the PayPal Sandbox client ID and secret first, then use **Webhook
setup** on the integration card. Reactant displays the webhook URL containing
the newly-created integration ID. Create the webhook in that same Sandbox
REST app, subscribe to `CHECKOUT.ORDER.APPROVED`, `PAYMENT.CAPTURE.COMPLETED`,
`PAYMENT.CAPTURE.PENDING`, `PAYMENT.CAPTURE.DENIED`,
`PAYMENT.CAPTURE.REFUNDED`, and `CHECKOUT.PAYMENT-APPROVAL.REVERSED`, then
save the webhook ID in Reactant. PayPal credentials and webhook ID are
encrypted at rest and never returned to the frontend.

The backend uses only the connected business's encrypted PayPal credentials;
it never falls back to the deployment's global PayPal credentials. Connect the
Sandbox app through the Integrations page and use its Test action before
enabling AgentCard. The merchant must be in a configured receiving country.
AgentCard is disabled until `AGENTCARD_ENABLED=true`; `PAYPAL_RECEIVING_COUNTRIES`
defaults to `US`. Do not enable live payments until PayPal has confirmed your
merchant eligibility and any required platform/partner approval.

Enable the agent's order and PayPal checkout permissions for the test
workspace. The agent can only submit catalog product IDs and quantities; the
backend loads current prices, validates stock, reserves inventory, and
calculates the amount. The customer must review and explicitly authorize the
checkout before PayPal is opened.

Required testing outcomes:

- The backend obtains a PayPal OAuth access token server-side.
- A checkout is created for the backend-validated order amount and currency.
- The customer completes the hosted Sandbox checkout.
- The PayPal webhook signature is verified using PayPal's verification API.
- The payment is independently checked before the order is marked paid.
- Return redirects do not mark a payment as successful.
- Duplicate webhooks and retries do not duplicate payment, order, or refund
  side effects.
- A receipt is generated and delivered to the Telegram customer after payment
  verification.
- An owner/admin can issue a partial or full refund with a stable
  `Idempotency-Key`; the ledger changes only after PayPal confirms it.

## 6. Public URL and webhook testing

Use the hosted HTTPS backend for provider testing. Do not expose Supabase
secrets through a tunnel. Register the exact Telegram and PayPal webhook URLs
against that public backend.

The deployed frontend is `https://getreactant.vercel.app` and the deployed
backend is `https://reactant.onrender.com`. For local testing, the frontend
uses `http://localhost:5173` and the backend uses
`http://localhost:8000`; include both frontend origins in
`ALLOWED_WEB_ORIGINS`.

## 7. AgentCard test order

Run the test in this order:

1. Sign in with an owner account.
2. Create/select a business.
3. Apply migration 0003 and set `SUPABASE_SECRET_KEY`,
   `CREDENTIALS_ENCRYPTION_KEY`, and the hosted HTTPS URLs in Render.
4. Connect and test the Telegram bot and PayPal Sandbox app from Integrations;
   complete the PayPal webhook setup in the integration card.
5. Add an active, agent-enabled catalog item with current price and stock.
6. Enable the Business Agent and its order and PayPal checkout permissions.
7. Set `AGENTCARD_ENABLED=true` in Render and redeploy after credentials and
   webhooks are ready.
8. Ask the agent about the item in Telegram, then explicitly confirm purchase
   and quantity when prompted.
9. Open the exact secure checkout URL sent by the agent, review the order, and
   authorize it before selecting PayPal.
10. Complete payment as the Sandbox customer. A redirect alone is not proof of
    payment; wait for backend verification.
11. Confirm the order is paid and a receipt is delivered to the Telegram chat.
12. If testing refunds, have an owner/admin call the refund endpoint with a
    stable `Idempotency-Key`; verify the partial/full refund in PayPal Sandbox
    and the AgentCard transaction ledger.

## Information needed from the product owner

Before provider testing, provide or configure:

- A Supabase project with the migrations applied.
- A public HTTPS backend URL for webhooks.
- A PayPal Sandbox business account, REST app credentials, and webhook ID.
- A Telegram bot token and approval to configure its webhook.
- The first test catalog product data and image.
- A confirmed country supported by the configured PayPal receiving-country
  allowlist.
- OpenRouter access to the configured vision-capable model.

Store deployment secrets in Render's environment settings or a secret manager.
Enter per-business Telegram and PayPal credentials only through the hosted
Integrations page over HTTPS; never send secrets through chat or commit them.
