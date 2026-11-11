# Reactant API Contract

**Version:** Draft v1  
**Audience:** Frontend and backend engineers  
**Status:** Implemented backend contract with explicitly marked planned integrations.

This contract describes the HTTP and realtime interfaces the Reactant web app
needs. The backend is implemented in FastAPI with Supabase Auth/Postgres and
the Python SDK. OpenAPI is generated from the running app; routes that return
`503` when required provider or runtime configuration is unavailable use
explicit error codes. Features that are not implemented are marked `planned`
in OpenAPI. This document distinguishes those limitations from implemented
request/response behavior.

## 1. API boundary

- **Base URL:** `https://reactant.onrender.com/api/v1`
- **JSON:** UTF-8 request and response bodies use `application/json`.
- **Authentication:** Supabase Auth (or the selected identity provider) issues
  short-lived access tokens. Send them as `Authorization: Bearer <access_token>`.
- **Tenant context:** Every business-scoped route includes `business_id`.
  The backend must confirm the caller is a member of that business on every
  request. Never trust a business ID supplied by the browser without checking
  membership.
- **IDs:** Opaque UUIDs unless a provider's external ID is explicitly required.
- **Time:** RFC 3339 timestamps in UTC.
- **Money:** Integer minor units plus ISO 4217 currency. Never use floating
  point values for payment calculations.
- **Default currency:** New businesses use USD unless another supported ISO
  4217 currency is explicitly selected. Country and currency are independent.
- **Pagination:** Cursor based. `limit` defaults to 25 and is capped at 100.
- **Versioning:** Breaking changes require a new major API prefix.
- **Documentation:** Publish `/api/v1/openapi.json` and Swagger UI at
  `/api/v1/docs` outside production. Both are disabled in production.

### Standard success envelope

Single-resource response:

```json
{
  "data": {
    "id": "uuid",
    "created_at": "2026-11-04T17:00:00Z"
  },
  "request_id": "req_01J..."
}
```

Collection response:

```json
{
  "data": [],
  "meta": {
    "next_cursor": null,
    "has_more": false
  },
  "request_id": "req_01J..."
}
```

### Standard error envelope

```json
{
  "error": {
    "code": "validation_error",
    "message": "The request could not be completed.",
    "fields": {
      "email": ["Enter a valid email address."]
    }
  },
  "request_id": "req_01J..."
}
```

Use the appropriate HTTP status, including `400` malformed request, `401`
unauthenticated, `403` not authorized, `404` not found, `409` conflicting
state, `412` stale `If-Match`, `422` validation failure, `428` missing
`If-Match`, `429` rate limited, and `5xx` unexpected server/provider failure.
Do not return `200` with an error-shaped payload. Messages must not disclose
secrets or another tenant's resource existence.

All successful API responses use the documented envelope, except `204 No
Content` operations, which have no response body. Authentication and provider
errors use the standard error envelope.

## 2. Authentication and workspace

Email/password, password recovery, email verification, and token refresh are
handled by the identity provider's documented auth API. The Reactant API
accepts the resulting access token. Do not build a second password store in
the application API.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/users/me` | Current user profile and identity-provider subject. |
| `GET` | `/businesses` | Workspaces for the authenticated user. |
| `POST` | `/businesses` | Create a workspace; creator becomes owner. |
| `GET` | `/businesses/{business_id}` | Get business profile and membership role. |
| `PATCH` | `/businesses/{business_id}` | Update business profile and regional preferences. |
| `GET` | `/businesses/{business_id}/members` | List workspace members. |
| `POST` | `/businesses/{business_id}/invitations` | Invite a team member by email and role. |
| `PATCH` | `/businesses/{business_id}/members/{member_id}` | Change a member's role. |
| `DELETE` | `/businesses/{business_id}/members/{member_id}` | Remove a member. |
| `POST` | `/invitations/{invitation_token}/accept` | Accept an invitation for the authenticated user. |

`business_id` membership roles are `owner`, `admin`, `staff`, and `read_only`.
Only `owner` and `admin` may manage integrations and agent policy. Approval
permissions are checked against the configured approver policy, not just
against the presence of an authenticated user.

### Create workspace

`POST /businesses`

Creating a workspace also creates the default Business Agent configuration
and approval policy in the same transaction. The new workspace must be ready
to load its agent settings immediately.

```json
{
  "name": "Olive & Oak Studio",
  "country": "GH",
  "currency": "USD",
  "timezone": "Africa/Accra"
}
```

### Update business profile

`PATCH /businesses/{business_id}`

```json
{
  "name": "Olive & Oak Studio",
  "support_email": "hello@example.com",
  "phone": "+233200000000",
  "website": "https://example.com",
  "country": "GH",
  "currency": "USD",
  "timezone": "Africa/Accra",
  "return_policy": "Unused items can be returned within 14 days.",
  "delivery_policy": "Delivery dates are confirmed at checkout."
}
```

### Invitations

`POST /businesses/{business_id}/invitations`

```json
{
  "email": "staff@example.com",
  "role": "staff"
}
```

Return an invitation ID, role, email, expiry, and status. Never return the
invitation's secret token after creation. Send it through the configured
invitation delivery mechanism. Invitation acceptance requires a signed-in,
email-confirmed Supabase user whose email matches the invitation.

`GET /businesses/{business_id}/members` returns each member's `id`, `user_id`,
`display_name`, `email`, `role`, and `created_at`. Resolve the display name and
email from the authenticated user profile without exposing unrelated profile
data. `PATCH /businesses/{business_id}/members/{member_id}` accepts a `role`
of `admin`, `staff`, or `read_only`; `DELETE` removes a member.
Only owners may change roles or remove members. Invitation creation returns
success only after the invitation has been durably stored and email delivery
has succeeded; otherwise return a clear error without implying an invite was
sent.

Business `GET` responses include an `ETag` containing the current version.
Profile `PATCH` requires `If-Match`; omitted fields remain unchanged. A missing
header returns `428`, and a stale version returns `412`. Workspace creation
and business updates are implemented; invitations require
`INVITATION_DELIVERY_URL` and `INVITATION_DELIVERY_TOKEN`.

## 3. Dashboard and business data

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/businesses/{business_id}/dashboard/summary` | Overview metrics, agent status, recent conversations, recent orders, and pending approvals. |
| `GET` | `/businesses/{business_id}/dashboard/setup` | Setup checklist and integration readiness. |
| `GET` | `/businesses/{business_id}/products` | Search/filter the combined owner-managed and storefront-synced catalog. |
| `POST` | `/businesses/{business_id}/products` | Create an owner-managed product using verified uploaded media assets. |
| `GET` | `/businesses/{business_id}/products/{product_id}` | Product, source, variants, availability, stock freshness, agent access, and image references. |
| `PATCH` | `/businesses/{business_id}/products/{product_id}` | Update an owner-managed product; reject writes to provider-owned fields on synced products. |
| `DELETE` | `/businesses/{business_id}/products/{product_id}` | Archive an owner-managed product and remove it from agent search. |
| `POST` | `/businesses/{business_id}/media/uploads` | Create a short-lived signed upload for a catalog image. |
| `POST` | `/businesses/{business_id}/media/{asset_id}/complete` | Validate a completed image upload before it can be attached to a product. |
| `GET` | `/businesses/{business_id}/media/{asset_id}/access` | Issue a short-lived, authenticated read URL for an authorized catalog image. |
| `GET` | `/businesses/{business_id}/audit-events` | Paginated audit history with filters. |
| `GET` | `/businesses/{business_id}/notifications` | Merchant-facing notification list. |
| `POST` | `/businesses/{business_id}/notifications/{notification_id}/read` | Mark a notification read. |

Summary supports `from` and `to` RFC 3339 query parameters. Product search
supports `q`, `cursor`, `limit`, `category`, `availability`, `source`
(`manual`, provider name, or `all`), and `agent_available`. Audit filters
include `actor`, `event_type`, `resource_type`, `from`, and `to`.

Product reads must be read-after-write consistent for the authenticated
business member. After a successful product `POST`, `PATCH`, or `DELETE`, a
subsequent `GET /products` must reflect the mutation without requiring a
client-side cache purge. Product mutation responses must return the canonical
resource in the standard `data` envelope. Responses should send
`Cache-Control: no-store` because catalog availability and agent permissions
are operational business data; clients may still keep their in-memory view
until the mutation response is received.

### Product catalog

The catalog is a private source of product facts and photos for the merchant
and Business Agent. It is not a public storefront and does not create public
product pages. `GET /products` can return both manually managed products and
provider-synced products. Each product includes a `source` (`manual` or the
provider key), an `agent_enabled` flag, a `status`, and ordered image asset
references. It also includes `image_urls`: short-lived signed delivery URLs
for validated manual images, or provider image URLs when available. These URLs
are scoped to the authorized business and must not be stored as permanent
identifiers. The browser may cache the image responses, but should refetch the
product resource when an image fails to load or a signed URL expires. Only authorized workspace members can manage products. The agent
can search only active products with `agent_enabled: true`.

Manual product create example:

```json
{
  "source": "manual",
  "name": "Handwoven market basket",
  "description": "Locally woven palm basket with leather handles.",
  "category": "Accessories",
  "price_minor": 18500,
  "currency": "USD",
  "stock_quantity": null,
  "status": "active",
  "agent_enabled": true,
  "image_asset_ids": ["uuid-image-1", "uuid-image-2"]
}
```

`stock_quantity: null` means stock is not tracked. It must not be interpreted
as available or in stock. A quantity of `0` means out of stock. Prices use
integer minor units and an explicit ISO 4217 currency. Manual product price
and description are merchant-provided facts. Storefront-synced product fields
remain provider-owned and cannot be overwritten through the manual edit route.

Image upload uses a three-step flow:

1. `POST /media/uploads` with `file_name`, `content_type`, `size_bytes`, and
   `purpose: "catalog_product"` returns a short-lived `asset_id`, upload URL,
   required headers, and expiry. The browser uploads with `PUT` and must send
   the returned required headers exactly.
2. The browser uploads bytes directly to the returned URL. The URL is scoped
   to one asset, one method, one content type, and a short expiry. Do not send
   the bytes through application logs.
3. `POST /media/{asset_id}/complete` verifies the actual object, size, and
   file signature. The API returns the validated asset record, which may then
   be referenced by a product create/update request.

For v1, accept JPEG, PNG, and WebP images up to 5 MiB each and at most six
images per manual product. Validate the real file signature, not just the
client-supplied MIME type. Reject malformed or unsupported files explicitly.
Keep originals private, strip unsafe metadata where appropriate, generate
delivery variants, and issue short-lived access only when a permitted
customer-channel action needs to send a product image. Do not expose storage
credentials or permanent public bucket paths.

Deleting a manual product archives it and prevents further agent retrieval.
An uploaded asset cannot be deleted while referenced by an active product;
unused assets are removed by a retention-aware cleanup job.

The authenticated media access route returns `{ "url": "...", "expires_at":
"..." }`. URLs are short-lived and scoped to the requested asset and
authorized business member. Product list responses return asset IDs, not permanent public URLs. Until the
authenticated media access route is available, clients must not fail the
entire catalog load when image URLs cannot be resolved. The product metadata
remains usable and the UI should show an unavailable-image state. Once the
route is implemented, clients can request fresh access URLs when loading
catalog images.

The setup response should describe each checklist item with `key`, `label`,
`status` (`not_started`, `in_progress`, `complete`, `attention_required`), and
an optional `action_url`.

## 4. Business settings

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/businesses/{business_id}/settings` | Read business, notification, and privacy preferences. |
| `PATCH` | `/businesses/{business_id}/settings` | Update allowed settings using partial-update semantics. |

The response includes the business profile fields above, notification
preferences (`new_conversations`, `approval_requests`, `payment_updates`,
`weekly_summary`), and privacy/retention policy metadata. A `PATCH` must leave
omitted fields unchanged. Do not include credentials in settings responses.
The settings response has an `ETag`; settings `PATCH` requires `If-Match` and
atomically applies business fields and notification preferences. Version
conflicts return `412`.

## 5. Integrations

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/businesses/{business_id}/integrations` | List configured provider connections and health. |
| `POST` | `/businesses/{business_id}/integrations/{provider}/authorization` | Start provider authorization where merchant consent is required. |
| `GET` | `/integrations/callback/{provider}` | Handle the provider callback and redirect to the frontend. |
| `POST` | `/businesses/{business_id}/integrations` | Connect a provider using a supported secure setup method. |
| `GET` | `/businesses/{business_id}/integrations/{integration_id}` | Read non-secret connection details and health. |
| `POST` | `/businesses/{business_id}/integrations/{integration_id}/test` | Test provider connectivity and permissions; return updated health. |
| `POST` | `/businesses/{business_id}/integrations/{integration_id}/sync` | Queue an initial or requested synchronization. |
| `DELETE` | `/businesses/{business_id}/integrations/{integration_id}` | Revoke/disconnect and schedule credential deletion. |

`provider` values include `woocommerce`, `telegram`, `paypal`, and later
`shopify`, `whatsapp`, and supported Meta channels. List and detail responses
include `id`, `provider`, `category`, `status`, `connected_at`,
`last_success_at`, `last_error`, `granted_scopes`, and sync status. Never return
access tokens, bot tokens, private keys, or OAuth client secrets.

WooCommerce setup request:

```json
{
  "provider": "woocommerce",
  "credentials": {
    "store_url": "https://store.example",
    "mcp_endpoint": "https://store.example/wp-json/woocommerce-ai/mcp",
    "consumer_key": "provided-over-tls",
    "consumer_secret": "provided-over-tls",
    "webhook_secret": "random 256-bit value generated by the frontend"
  }
}
```

`mcp_endpoint` is optional. When supplied, the backend validates the official
WooCommerce MCP endpoint over HTTPS using the `X-MCP-API-Key` header and a
least-privilege WooCommerce key. The endpoint must belong to the connected
store or use the official `public-api.wordpress.com` host. Reactant does not
accept arbitrary MCP hosts or expose MCP credentials to the agent.

Telegram setup request:

```json
{
  "provider": "telegram",
  "credentials": {
    "bot_token": "provided-over-tls",
    "webhook_secret": "random 256-bit value generated by the frontend"
  }
}
```

PayPal setup request:

```json
{
  "provider": "paypal",
  "credentials": {
    "consumer_key": "PayPal REST app client ID",
    "consumer_secret": "PayPal REST app secret",
    "webhook_id": "PayPal webhook ID"
  }
}
```

Credential submission is allowed only over TLS to an authenticated,
business-authorized endpoint. Encrypt credentials at rest, redact them from
logs and traces, and never echo them in any response. Prefer OAuth/authorization
redirects when the provider supports them. The browser-generated webhook
secret must never be persisted in browser storage or returned by the API. The
backend uses it to configure WooCommerce webhook signatures or Telegram's
`setWebhook` `secret_token`. For PayPal, the backend exchanges REST app
credentials for an OAuth 2.0 access token server-side and verifies webhook
events using the configured webhook ID. A valid Fernet
`CREDENTIALS_ENCRYPTION_KEY` is required.

The current credential route accepts WooCommerce (`store_url`, `consumer_key`,
`consumer_secret`, `webhook_secret`), Telegram (`bot_token`, `webhook_secret`),
and PayPal (`consumer_key`, `consumer_secret`, `webhook_id`) and returns a
`pending` integration. Credential acceptance is not proof that a provider is
reachable, configured, or synchronized. Until authorization, webhook
provisioning, connection tests, and sync workers are implemented, those
operations must return explicit `503` errors and the frontend must show the
error rather than mark the connection as healthy.

Provider sandbox preparation, webhook URLs, required PayPal events, Telegram
BotFather steps, and the first catalog test sequence are documented in
[`setup.md`](./setup.md). Each business connects its own PayPal merchant app;
Reactant does not hold or receive merchant funds.

Provider implementation references (official documentation):

- [WooCommerce REST API keys](https://woocommerce.com/document/woocommerce-rest-api/)
- [Telegram bots FAQ](https://core.telegram.org/bots/faq) and
  [Bot API setWebhook](https://core.telegram.org/bots/api#setwebhook)
- [PayPal Checkout standard integration](https://developer.paypal.com/docs/checkout/standard/integrate/)
- [PayPal webhook signature verification](https://developer.paypal.com/docs/api/webhooks/v1/#verify-webhook-signature_post)

PayPal is limited to creating customer checkout sessions and verifying
customer payments. Reactant and the Business Agent must not read merchant
balances, create payouts, or transfer merchant funds.

### Frontend provider-connection flow

The browser must never authenticate to PayPal, WooCommerce, or Telegram with
merchant secrets. These are server-side integrations:

1. The signed-in owner/admin opens the Integrations screen.
2. The frontend collects provider credentials only in an in-memory form. Do not
   put them in local storage, URL parameters, analytics events, or error
   reports.
3. Submit the credentials once to
   `POST /businesses/{business_id}/integrations` over HTTPS with the Supabase
   access token. The response is a redacted integration record; it never
   contains credentials.
4. Use the provider Test action to validate credentials. Display `connected`
   only after the backend reports a successful provider test.
5. Disable Sync when that integration does not support product synchronization.
   Do not retry provider actions automatically.
6. On disconnect, call the backend `DELETE` endpoint and remove the connection
   from the UI only after a successful response.

For PayPal specifically, the merchant enters the PayPal REST app client ID,
client secret, and webhook ID in the owner/admin setup form. The frontend does
not use the PayPal JavaScript SDK for merchant authentication and must never
receive the client secret. The backend exchanges credentials server-side,
validates them before marking the integration connected, and verifies webhook
signatures.
OAuth authorization routes are listed in this contract but are currently
implemented for Shopify. Shopify authorization requires the backend
`SHOPIFY_CLIENT_ID`, `SHOPIFY_CLIENT_SECRET`, and an exact registered callback
URL. The frontend submits only the shop domain and follows the returned
`authorization_url`; it never receives the Shopify access token.

### AgentCard customer checkout flow

The Business Agent can prepare a transaction only after explicit purchase
intent and only from active catalog product IDs and quantities. It never sets
prices, shipping, discounts, or totals. The public checkout endpoints are
token-protected; no customer Supabase account is required.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/agentcard/checkout/{token}` | Read immutable business, item, amount, and expiry details. |
| `POST` | `/agentcard/checkout/{token}/authorize` | Record explicit customer consent for the displayed snapshot. |
| `POST` | `/agentcard/checkout/{token}/payment` | Create or resume the merchant's PayPal checkout. |
| `POST` | `/agentcard/checkout/{token}/capture` | Ask the backend to capture and independently verify the PayPal order. |
| `GET` | `/agentcard/checkout/{token}/status` | Poll verified payment/refund state and receipt URL. |

Both `authorize` and `payment` require `{"accepted": true}`. `capture` requires
`{"provider_order_id": "<PayPal order ID>"}`. A PayPal return URL is only a
navigation event: the browser must show **Payment being verified** until the
backend reports `paid`. Checkout URLs expire after 30 minutes and carry a
high-entropy token stored only as a hash.

The consent record is `internal-consent/v1`; it is not an AP2 mandate or proof
of AP2 conformance. The backend stores immutable order snapshots, calculates
amounts from current catalog data, verifies the PayPal order reference, capture
status, amount, and currency, and uses signed webhooks plus a reconciliation
worker for delayed provider results.

### AgentCard business transaction management

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/businesses/{business_id}/agentcard/transactions/{transaction_id}` | Read a transaction for a workspace member. |
| `POST` | `/businesses/{business_id}/agentcard/transactions/{transaction_id}/cancel` | Owner/admin cancellation of an unpaid transaction. |
| `POST` | `/businesses/{business_id}/agentcard/transactions/{transaction_id}/refunds` | Owner/admin partial or full refund through the connected PayPal account. |

Refund requests require an `Idempotency-Key` header and a JSON body containing
`amount_minor` and optional `reason`. The backend reserves the remaining
refundable balance, calls PayPal using the merchant's encrypted credentials,
and updates the ledger only after verifying the provider refund. Do not treat
an accepted or pending refund as completed.

The legacy order checkout endpoint below remains a separate workflow. It
currently supports its approval branch; AgentCard customer purchases use the
dedicated tokenized endpoints above.


## 6. Business Agent configuration

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/businesses/{business_id}/agent` | Read agent status, instructions, policies, and permissions. |
| `PATCH` | `/businesses/{business_id}/agent` | Update allowed agent settings and action policy. |
| `POST` | `/businesses/{business_id}/agent/test` | Run a non-customer-facing configuration test. |

Example `PATCH`:

```json
{
  "enabled": true,
  "business_context": "We sell home goods and ship across Ghana.",
  "tone": "warm_helpful",
  "handoff_rule": "when_uncertain",
  "permissions": {
    "answer_product_questions": true,
    "share_product_images": true,
    "create_carts_and_orders": true,
    "create_paypal_checkout": false
  },
  "approval_policy": {
    "require_approval_for_checkout": true,
    "checkout_threshold_minor": 100000,
    "currency": "USD",
    "approver_member_ids": []
  }
}
```

`checkout_threshold_minor: null` means every checkout needs approval when
`require_approval_for_checkout` is true. The backend must revalidate order
ownership, eligibility, current product price, inventory, currency, and
amount immediately before creating a checkout. Frontend values and LLM tool
arguments are never authoritative.

The runtime builds a tenant-specific system instruction for every agent run. It
includes the business name, country, currency, return and delivery policies,
merchant-authored context, tone, handoff rule, permissions, and approval policy.
The instruction requires catalog-grounded answers, treats unknown stock as
unknown, separates public web facts from business facts, resists prompt
injection, and prohibits claiming that orders, checkout, payments, refunds, or
other side effects completed without a verified backend result. Owner-agent
messages use a private operational version of this instruction; customer
messages use a separate version that never exposes internal configuration or
owner-channel content.

## 7. Customer conversation channel

These routes are only for customer-facing conversations and human replies.
They must not be used for owner/agent discussions.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/businesses/{business_id}/conversations` | List/filter customer conversations. |
| `GET` | `/businesses/{business_id}/conversations/{conversation_id}` | Read conversation and customer/order context. |
| `GET` | `/businesses/{business_id}/conversations/{conversation_id}/messages` | Read customer-visible and staff-only thread history with visibility tags. |
| `POST` | `/businesses/{business_id}/conversations/{conversation_id}/messages` | Send a staff reply to the customer through its provider channel. |
| `PATCH` | `/businesses/{business_id}/conversations/{conversation_id}` | Update assignment or status (`open`, `needs_reply`, `resolved`). |
| `POST` | `/businesses/{business_id}/conversations/{conversation_id}/handoff` | Accept or return a conversation handoff between agent and staff. |
| `POST` | `/businesses/{business_id}/conversations/{conversation_id}/read` | Mark the customer thread read. |

List query parameters: `status`, `channel`, `assignee_id`, `q`, `cursor`, and
`limit`. Reply body:

The conversation list response must include `id`, `channel`, `status`,
`customer_name`, `unread`, `updated_at`, and `last_message`. `last_message` is
either `null` or `{ "text": "...", "created_at": "RFC3339 timestamp" }`.
These fields power the inbox list; they must not be inferred from sample data
or client-side placeholders. The conversation detail response also includes
customer context and order references. The messages route returns ordered
messages with `sender_type`, `text`, `visibility`, `delivery_status`, and
`created_at`.

```json
{
  "text": "The sand colour is available in Queen and King sizes.",
  "visibility": "customer"
}
```

The `visibility` value must be `customer` for this endpoint. Internal notes
must use a separate staff-only endpoint/model and must never be delivered to a
customer provider. Customer messages and owner-assistant messages have
different IDs, storage scope, access policy, and realtime event topics.
Every customer reply requires an `Idempotency-Key`. The endpoint returns
`202 Accepted` when the message and delivery request have been persisted to
the outbox. This is **queued, not delivered**: the outbound provider delivery
worker is not implemented. Display an explicit queued/pending state and do
not tell the customer the reply was delivered.

### Customer images

Telegram customer photos and image documents are fetched server-side using the
connected bot token. The website widget accepts up to three JPEG, PNG, or WebP
images in its existing `POST /public/widgets/sessions/messages` body:

```json
{
  "text": "Can you tell me what is in this picture?",
  "images": ["data:image/jpeg;base64,<base64-encoded-image>"]
}
```

The widget request must include its origin-bound session token. Each image is
limited to 5 MB; all images in one message together are limited to 5 MB.
Images are decoded and re-encoded as JPEG, then stored in the private
`customer-chat-media` bucket. Business inbox and widget message responses
receive short-lived signed URLs; raw storage paths are not returned.

The Business Agent receives actual image bytes as multimodal model input, not
just a text placeholder. When an image is present, the backend selects
`OPENROUTER_VISION_MODEL_ID` (default `google/gemini-2.5-flash`) instead of the
text model. Verify the account can access a vision-capable model; provider
availability, latency, and charges apply. The model must treat image text as
untrusted input and describe only visible details. Telegram and website chat
are the currently supported customer-image channels; WhatsApp has no active
adapter.

## 8. Private Agent-to-Owner channel

The owner assistant is a private business workspace conversation. It is
separate from the customer inbox, channel webhooks, customer transcript,
outbound customer message tools, and customer delivery. Use it for:

- Questions where business context or a policy is unclear.
- Approval requests for a sensitive action such as a customer checkout.
- Exceptions, integration problems, or requests for human attention.
- Agent summaries and owner instructions.

Owner messages may inform the business agent's future work, but must not be
inserted into a customer transcript or forwarded to Telegram, WhatsApp, email,
or another customer channel.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/businesses/{business_id}/owner-assistant/status` | Report whether the Strands/OpenRouter owner agent is ready. |
| `GET` | `/businesses/{business_id}/owner-assistant/thread` | Get or create the single private owner thread and latest messages. |
| `GET` | `/businesses/{business_id}/owner-assistant/messages` | Paginate private thread messages. |
| `POST` | `/businesses/{business_id}/owner-assistant/messages` | Send an owner/team message to the business agent. |
| `GET` | `/businesses/{business_id}/owner-assistant/runs/{run_id}` | Read the status of an accepted background agent run. |
| `POST` | `/businesses/{business_id}/owner-assistant/messages/{message_id}/read` | Mark a private agent message read. |

Owner send body:

```json
{
  "text": "For same-day dispatch, confirm with me before promising a time.",
  "client_message_id": "client-generated-uuid"
}
```

Use `client_message_id` or `Idempotency-Key` to make retries safe. The
response includes the persisted owner message, `agent_run_id`, and the current
`agent_run_status` (`queued`, `running`, `succeeded`, or `failed`). The
endpoint returns `202 Accepted` after the message and run are atomically
persisted. The Strands worker processes runs outside the request path. Poll
`GET /businesses/{business_id}/owner-assistant/runs/{run_id}` to update the
status; render `queued` and `running` as pending, and do not claim the agent
answered until an agent response message exists.

The status endpoint returns `provider: "strands"`, `enabled`, `available`,
`model_id`, and a safe `reason` (`ready`, `disabled`,
`missing_openrouter_key`, or `missing_service_key`). The owner UI must disable
the composer unless `available` is true and must show configuration guidance
instead of presenting a successful-looking unavailable channel. Owner messages
are private workspace communication in both directions: the owner/team sends
messages to Strands, and the worker persists Strands responses back into the
same owner thread. They are never sent to customer channels.

Run status response:

```json
{
  "data": {
    "id": "uuid",
    "status": "running",
    "created_at": "2026-11-04T17:00:00Z",
    "started_at": "2026-11-04T17:00:01Z",
    "completed_at": null,
    "error_code": null
  },
  "request_id": "req_01J..."
}
```

Terminal states are `succeeded` (the private agent reply has been persisted)
and `failed` (the worker exhausted its bounded retries). `error_code` is
generic and must not be used to expose provider details or secrets.

The worker is opt-in via `STRANDS_AGENT_ENABLED=true` and requires
`SUPABASE_SECRET_KEY` plus the backend-only `OPENROUTER_API_KEY`. Strands uses
OpenRouter's OpenAI-compatible API endpoint and defaults to the `openrouter/free`
model router; set `OPENROUTER_MODEL_ID` to select a different OpenRouter model.
Free model availability, tool support, and rate limits can vary. Its only tool
is a read-only, business-scoped search over active products whose
`agent_enabled` flag is true. It cannot change data, create orders, or contact
customers. Do not attach an MCP server unless one is explicitly configured
and reviewed; the current local catalog tool does not need MCP.

Private message representation:

```json
{
  "id": "uuid",
  "thread_id": "uuid",
  "sender": {
    "type": "agent",
    "id": "agent-id",
    "display_name": "Business agent"
  },
  "kind": "approval_request",
  "text": "May I create a checkout link for the validated customer order?",
  "approval_id": "uuid",
  "created_at": "2026-11-04T17:00:00Z",
  "read_at": null
}
```

Allowed `kind` values: `text`, `clarification`, `approval_request`,
`exception`, `status_update`, and `summary`. A message of kind
`approval_request` references the canonical approval resource. Approval UI
must call the approval decision endpoint below and reflect its server result;
it must not treat a chat message itself as an approval.

The agent runtime creates private owner messages through an internal
service-only command:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/internal/v1/businesses/{business_id}/owner-assistant/messages` | Persist and enqueue a trusted agent-to-owner message. |

This command is not available to browsers, customers, or normal user bearer
tokens. Authenticate with service identity, validate the business and agent
run, enforce idempotency, and publish an owner-channel event through the
outbox. A `approval_request` must reference an existing pending approval.
Owner messages that contain a question or exception must not imply that
payment, inventory, or order state has changed.

## 9. Approvals

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/businesses/{business_id}/approvals` | List pending and historical approval requests. |
| `GET` | `/businesses/{business_id}/approvals/{approval_id}` | Read request, impact, expiry, and decision state. |
| `POST` | `/businesses/{business_id}/approvals/{approval_id}/decision` | Approve or reject a pending action. |

List filters: `status`, `action_type`, `cursor`, and `limit`. Decision:

```json
{
  "decision": "approved",
  "note": "The order amount and contents are correct."
}
```

Use `Idempotency-Key` for decision requests. The backend must atomically
transition a pending approval, verify the caller's approver permission, and
record actor, timestamp, decision, and optional note. Replaying a decision
must not execute the underlying action a second time.
The approval decision transition is implemented; downstream actions still
depend on their relevant worker or provider adapter.

## 10. Orders and checkout

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/businesses/{business_id}/orders` | List/filter orders. |
| `POST` | `/businesses/{business_id}/orders` | Create a merchant-authorized order from a validated cart. |
| `GET` | `/businesses/{business_id}/orders/{order_id}` | Read order, line items, payment, and event history. |
| `POST` | `/businesses/{business_id}/orders/{order_id}/checkout` | Create a PayPal customer checkout session or return an approval-required state. |
| `POST` | `/businesses/{business_id}/orders/{order_id}/cancel` | Cancel an eligible unpaid order. |

Order list filters: `status`, `payment_status`, `q`, `from`, `to`, `cursor`,
and `limit`. Checkout uses `Idempotency-Key`. Successful checkout response:

```json
{
  "data": {
    "order_id": "uuid",
    "payment_id": "uuid",
    "provider": "paypal",
    "status": "checkout_created",
    "checkout_url": "https://www.paypal.com/checkout/...",
    "amount_minor": 62000,
    "currency": "USD",
    "expires_at": "2026-11-04T18:00:00Z"
  }
}
```

If policy requires review, return `202 Accepted` with
`status: "approval_required"` and `approval_id`; do not create the provider
checkout session before approval. Provider redirects are not proof of
payment. Only verified provider events/API status can transition payment and
order state to paid. Never add payout, balance, or fund-transfer endpoints to
the agent-facing surface.
The approval-gating flow is implemented. If approval is not needed, the
PayPal checkout adapter is not yet available and the endpoint returns `503`;
the frontend must show a retryable unavailable state, not a checkout success.

## 11. Global search

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/businesses/{business_id}/search` | Search customer conversations, orders, products, and navigable workspace resources. |

Query parameters: required `q`; optional `types` (comma-separated),
`cursor`, and `limit`. Each result includes `type`, `id`, `title`, `subtitle`,
and a typed `resource_url`. Apply business authorization before searching or
returning a result. Exclude private owner-assistant messages unless a future
explicit owner-channel search option is enabled for authorized team members.

## 12. Realtime events

Realtime is used to update the inbox, owner thread, approvals, notifications,
and integration/order status without polling.

1. Authenticated client requests
   `POST /api/v1/businesses/{business_id}/realtime-ticket`.
2. The response includes a random, one-use `ticket` with a 60-second expiry
   and a WebSocket URL.
3. Client opens the returned WebSocket URL with the offered subprotocol
   `reactant-ticket.<ticket>`; the ticket is not a URL parameter. The server consumes the ticket,
   verifies its user and business membership, and authorizes event topics.
4. Send the `subscribe` frame immediately after connection. Reconnect by
   requesting a new ticket and resuming with the last opaque `cursor`, either
   in the URL's `cursor` query parameter or in the subscribe frame. Do not put
   long-lived bearer tokens in URLs or logs.

Client frame:

```json
{
  "type": "subscribe",
  "topics": ["owner_assistant", "approvals", "notifications"],
  "cursor": "opaque-cursor-from-the-last-event"
}
```

Server event:

```json
{
  "id": "uuid",
  "type": "owner_assistant.message_created",
  "business_id": "uuid",
  "occurred_at": "2026-11-04T17:00:00Z",
  "data": {
    "message_id": "uuid",
    "thread_id": "uuid"
  },
  "cursor": "opaque-cursor-from-this-event"
}
```

Required event types include:

- `conversation.created`, `conversation.updated`,
  `conversation.message_created`
- `owner_assistant.message_created`, `owner_assistant.message_read`
- `approval.created`, `approval.updated`, `approval.decided`
- `order.created`, `order.updated`, `payment.updated`
- `integration.updated`, `catalog.sync_updated`
- `notification.created`

Owner assistant events are only delivered to authorized business members and
must never be included in customer channel events. Persist events before
publishing; support event IDs and reconnect/resume cursors to avoid missed
updates. The current backend polls the durable outbox and sends an opaque
cursor with each event. An initial connection without a cursor receives new
events only; retain the last cursor for reconnects. Tickets expire after 60
seconds, and the WebSocket origin must be included in `ALLOWED_WEB_ORIGINS`.
WebSocket frames do not use the HTTP success envelope.

## 13. Provider webhooks

Provider webhooks are server-to-server endpoints and do not use merchant
browser bearer tokens. Verify provider signatures/secrets, enforce request
size limits, deduplicate provider event IDs, persist the event before
acknowledging it, and process asynchronously.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/webhooks/woocommerce/{integration_id}` | Store/catalog/order change events. |
| `POST` | `/webhooks/telegram/{channel_id}` | Inbound customer messages and provider updates. |
| `POST` | `/webhooks/paypal/{integration_id}` | Checkout/payment events, verified against PayPal. |
| `POST` | `/webhooks/whatsapp/{channel_id}` | Future inbound message and delivery events. |

Return `2xx` only after durable receipt. A duplicate valid event should receive
a successful acknowledgement without repeating side effects. Keep webhook
responses small; agent execution belongs in an asynchronous worker.

## 14. Common headers and concurrency

- `Authorization: Bearer <access_token>` on authenticated API calls.
- `Content-Type: application/json` on JSON writes.
- `Idempotency-Key: <unique-operation-key>` on order creation, checkout,
  approval decisions, and customer replies. Owner-assistant messages accept
  `client_message_id` or `Idempotency-Key`.
- Optional `X-Request-ID` for client correlation; server always returns
  `request_id`.
- Use `ETag`/`If-Match` for concurrent edits to business profile, business
  settings, and agent configuration. `If-Match` is required (`428` if absent)
  and stale versions return `412 Precondition Failed`.
- Reuse an idempotency key only when retrying the same operation. A different
  payload with an existing key returns `409`.

## 15. Frontend integration requirements

1. Obtain and refresh the user's Supabase Auth session in the frontend, then
   send the current access token as `Authorization: Bearer <access_token>` on
   every authenticated API request. Never send the Supabase service-role key.
2. Select a business from `GET /businesses`; pass its ID only in the route and
   still handle `404`/`403` authorization failures. Do not infer access from a
   cached business ID.
3. Preserve each returned `ETag` and send it as `If-Match` on business,
   settings, and agent configuration edits. On `412`, reload and ask the user
   to reconcile rather than silently retrying an overwrite. Send `If-Match`
   on every such patch; a missing precondition returns `428`.
4. Generate a unique `Idempotency-Key` per logical side effect and retain it
   for network retries. Do not generate a new key just because a request timed
   out. Handle `409` by refreshing state and reporting the conflict.
5. Render customer replies as **queued** after `202`; their delivery worker is
   not available. For owner-assistant requests, use the returned `agent_run_id`
   to poll the run-status endpoint; do not show an agent response until an
   agent message exists.
6. For integrations, keep provider credentials in memory only, submit them
   once over HTTPS, and render `pending` as unverified. Hide/disable Test and
   Sync while their backend routes return planned `503` responses. For
   checkout, handle `202 approval_required` separately from `503` PayPal
   adapter unavailability. Never interpret a redirect as payment confirmation;
   refresh the order until the backend verifies payment.
7. For realtime, request a fresh ticket, offer it as the
   `reactant-ticket.<ticket>` WebSocket subprotocol, subscribe to authorized
   topics, and persist the last opaque cursor for reconnect. Reacquire tickets
   on reconnect; never place a bearer token in the URL.
8. For catalog image upload, use the short-lived returned upload URL and
   required headers, then call `complete`. Only attach an asset after the
   backend confirms it is validated.
9. Treat planned integration OAuth/test/sync routes and the WhatsApp webhook
   as unavailable (`503`); show a clear disabled or retry state rather than a
   success-shaped fallback. The agent test route requires runtime configuration
   and invokes the model, which may incur provider charges.
10. Render standard API error envelopes by `error.code`; use `request_id` for
    support diagnostics and never display raw provider/database error details.

## 16. Frontend-to-endpoint mapping

| Frontend surface | API resources |
|---|---|
| Landing page | Public/static content; no private API call. |
| Signup and login | Identity-provider signup/login/recovery; then `GET /users/me`. |
| Workspace switcher | `GET /businesses`; `GET /businesses/{business_id}`. |
| Overview | Dashboard summary, setup, realtime events. |
| Customer inbox | Conversations, customer messages, assignment/handoff, realtime events. |
| Agent messages | Owner-assistant thread/messages, approval decisions, realtime events. This is not the customer inbox. |
| Orders | Orders list/detail, checkout, realtime order/payment events. |
| Approvals | Approvals list/detail/decision, realtime approval events. |
| Integrations | Integrations list, authorization, test, sync, disconnect. |
| Business Agent | Agent configuration, permissions, realtime status. |
| Settings | Business settings, members/invitations, notifications, privacy. |
| Search | Business-scoped global search. |

## 17. Minimum implementation and acceptance checklist

- [x] Implement backend routes in sections 2-13 or explicitly mark unavailable
  routes `planned` in generated OpenAPI.
- [ ] Enforce membership and resource ownership checks on every
  business-scoped request.
- [ ] Add request/response Pydantic models and contract tests for all
  implemented operations.
- [ ] Add generated OpenAPI to CI and fail on schema drift or undocumented
  breaking changes.
- [ ] Keep customer conversations and the private Agent-to-Owner channel
  separate in storage, authorization, search, realtime topics, and provider
  delivery.
- [ ] Route agent clarification/approval/exception messages to the private
  owner thread; link approval messages to the canonical approval record.
- [ ] Enforce permission checks, approval thresholds, backend order
  revalidation, and audit records before checkout side effects.
- [ ] Verify PayPal webhook signatures and payment state with PayPal before an
  order is marked paid.
- [ ] Do not expose merchant balances, payouts, or fund transfers to the
  Business Agent.
- [ ] Test responsive web layouts separately. API correctness does not replace
  mobile UI testing.

The Supabase SQL migration has not been applied to a project. Apply
`backend/src/supabase/migrations/0001_core_schema.sql` manually in a
non-production Supabase project first, and use new numbered migration files
for all later schema changes.
