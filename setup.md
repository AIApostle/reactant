# Reactant MVP Setup

This setup follows the product workflow in [`prd.md`](./prd.md):

1. A business creates an internal catalog.
2. The business connects a Telegram bot.
3. The Business Agent answers from approved catalog data.
4. The backend creates a validated order and a PayPal hosted checkout.
5. PayPal confirms payment through a verified webhook before the order becomes paid.

Reactant never receives or stores money. Each business connects its own PayPal
merchant application, so PayPal sends the payment to that business's PayPal
account. Reactant only creates checkout sessions and verifies payment state.

## What is already in the repository

- Supabase Auth and business tenancy.
- Manual product catalog and private product image uploads.
- Encrypted integration credential storage.
- Telegram and PayPal webhook endpoints.
- PayPal webhook signature verification code.
- Approval-gated checkout behavior.
- Strict tenant authorization and idempotency requirements.

The following are **not yet enabled in the current backend**:

- Provider connectivity tests and health transitions.
- Telegram `getMe`, `setWebhook`, inbound message normalization, and outbound
  message delivery.
- PayPal OAuth token exchange for checkout creation.
- PayPal order/capture creation and payment reconciliation.
- Provider sync workers.

Submitting credentials currently creates a `pending` integration only. It is
not proof that the provider is connected. Do not enter production credentials
until these adapters are implemented and tested.

## 1. Prepare the hosted environment

For the hosted deployment, set these values in the deployment dashboards.
Do not rely on local `.env` files for Vercel or Render:

```bash
cp backend/.env.example backend/.env
cp frontend/app/.env.example frontend/app/.env.local
```

### Render backend environment

```dotenv
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_PERISHABLE_KEY=<server-compatible-supabase-key>
SUPABASE_SECRET_KEY=<server-only-secret-key>
CREDENTIALS_ENCRYPTION_KEY=<fernet-key>
ALLOWED_WEB_ORIGINS=https://reactent-theta.vercel.app
PAYPAL_API_BASE_URL=https://api-m.sandbox.paypal.com
PAYPAL_CLIENT_ID=<sandbox-rest-app-client-id>
PAYPAL_SECRET_KEY=<sandbox-rest-app-secret>
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

`PUBLIC_API_BASE_URL` is a deployment/tunnel value used when constructing
provider webhook URLs; it is not currently read from backend settings. The
backend must still be reachable at the public HTTPS host before Telegram or
PayPal can deliver webhooks.

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
3. Apply each later numbered migration in order when one is provided.
4. Enable email/password Auth.
5. For local testing, keep email confirmation disabled or use confirmed test
   users.
6. Confirm the private `product-media` storage bucket exists.

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
   integration adapter configuration.
8. **Current status:** the Integrations page can store the bot token and
   webhook secret encrypted, but the current backend does not yet call
   `getMe`/`setWebhook` or deliver outbound messages. Do not mark the bot
   connected based on credential submission.
9. After the Telegram adapter is implemented, connect it as an owner/admin and
   verify the bot with a test message from a second Telegram account.

Required testing outcomes:

- Telegram `getMe` validates the token.
- Telegram `setWebhook` succeeds with the public HTTPS webhook URL.
- Incoming updates are signature/secret checked and deduplicated.
- The conversation is associated with the correct business.
- Outbound replies are sent only by a backend worker using the stored bot
  token.

## 5. Prepare PayPal Sandbox

Use the PayPal Developer Dashboard, not a personal password:

1. Create a PayPal Sandbox business account for the test business.
2. Create a Sandbox REST app under that business account.
3. Save the Sandbox client ID and client secret securely.
4. Create a webhook for:

   ```text
   https://<public-backend-host>/webhooks/paypal/<integration_id>
   ```

   The integration ID is available after the initial connection record is
   created. If PayPal requires the webhook before the ID is known, create the
   integration first, then finish webhook configuration and save its webhook
   ID.
5. Subscribe to at least these events:
   - `CHECKOUT.ORDER.APPROVED`
   - `PAYMENT.CAPTURE.COMPLETED`
   - `PAYMENT.CAPTURE.DENIED`
   - `PAYMENT.CAPTURE.REFUNDED`
   - `CHECKOUT.PAYMENT-APPROVAL.REVERSED`
6. Set `PAYPAL_API_BASE_URL=https://api-m.sandbox.paypal.com`.
7. Use a Sandbox personal account as the customer and the Sandbox business
   account as the merchant.

The PayPal client ID, client secret, and webhook ID are submitted through the
authenticated Integrations page over HTTPS. They are encrypted at rest and
never returned to the frontend. PayPal credentials must remain server-side.

**Current status:** the current backend can verify a PayPal webhook signature
after an integration exists, but it does not yet create PayPal checkout orders,
capture payments, reconcile payment state, or transition the integration to
`connected`. The checkout endpoint therefore returns
`paypal_unavailable` when approval is not required. Sandbox credentials alone
will not make checkout work until the PayPal adapter is implemented.

Required testing outcomes:

- The backend obtains a PayPal OAuth access token server-side.
- A checkout is created for the backend-validated order amount and currency.
- The customer completes the hosted Sandbox checkout.
- The PayPal webhook signature is verified using PayPal's verification API.
- The payment is independently checked before the order is marked paid.
- Replayed webhook events do not duplicate payment or order side effects.

## 6. Public URL and local webhook testing

For future provider testing, expose the backend through an HTTPS tunnel or a
deployed development backend. Do not expose Supabase secrets through the
tunnel. Register the exact Telegram and PayPal webhook URLs against that
public backend.

The deployed frontend is `https://reactent-theta.vercel.app` and the deployed
backend is `https://reactant.onrender.com`. For local testing, the frontend
uses `http://localhost:5173` and the backend uses
`http://localhost:8000`; include both frontend origins in
`ALLOWED_WEB_ORIGINS`.

## 7. Test order

Run the test in this order:

1. Sign in with an owner account.
2. Create/select a business.
3. Add and approve at least one catalog product and image.
4. Confirm the Telegram and PayPal adapters are enabled in the backend.
5. Connect and verify Telegram.
6. Connect PayPal Sandbox and verify the webhook.
7. Send a Telegram product question.
8. Confirm the agent uses only the catalog facts.
9. Create an order with a stable `Idempotency-Key`.
10. Confirm any approval requirement.
11. Open the PayPal Sandbox checkout.
12. Complete payment as the Sandbox customer.
13. Confirm only a verified webhook changes the order to paid.

## Information needed from the product owner

Before provider testing, provide or configure:

- A Supabase project with the migrations applied.
- A public HTTPS backend URL for webhooks.
- A PayPal Sandbox business account, REST app credentials, and webhook ID.
- A Telegram bot token and approval to configure its webhook.
- The first test catalog product data and image.
- The desired test currency and approval threshold.

Send secrets through the local `.env` files or a secret manager, never in chat.
