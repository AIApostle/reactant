# Reactant API Contract

**Version:** Draft v1  
**Audience:** Frontend and backend engineers  
**Status:** Proposed integration contract. Backend routes are not implemented yet.

This contract describes the HTTP and realtime interfaces the Reactant web app
needs. The backend directory is currently an empty FastAPI scaffold, so these
routes are a concrete proposal for implementation, not a claim that the
endpoints already exist. Backend engineers should generate and publish the
OpenAPI schema from the implemented Pydantic models and keep it aligned with
this document.

## 1. API boundary

- **Base URL:** `https://api.<reactant-domain>/api/v1`
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
  `/api/v1/docs` outside production, or behind staff authentication in
  production.

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
unauthenticated, `403` not authorized, `404` not found, `409` stale/conflicting
state, `422` validation failure, `429` rate limited, and `5xx` unexpected
server/provider failure. Do not return `200` with an error-shaped payload.
Messages must not disclose secrets or another tenant's resource existence.

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
invitation delivery mechanism.

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
| `GET` | `/businesses/{business_id}/audit-events` | Paginated audit history with filters. |
| `GET` | `/businesses/{business_id}/notifications` | Merchant-facing notification list. |
| `POST` | `/businesses/{business_id}/notifications/{notification_id}/read` | Mark a notification read. |

Summary supports `from` and `to` RFC 3339 query parameters. Product search
supports `q`, `cursor`, `limit`, `category`, `availability`, `source`
(`manual`, provider name, or `all`), and `agent_available`. Audit filters
include `actor`, `event_type`, `resource_type`, `from`, and `to`.

### Product catalog

The catalog is a private source of product facts and photos for the merchant
and Business Agent. It is not a public storefront and does not create public
product pages. `GET /products` can return both manually managed products and
provider-synced products. Each product includes a `source` (`manual` or the
provider key), an `agent_enabled` flag, a `status`, and ordered image asset
references. Only authorized workspace members can manage products. The agent
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
   required headers, and expiry.
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

## 5. Integrations

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/businesses/{business_id}/integrations` | List configured provider connections and health. |
| `POST` | `/businesses/{business_id}/integrations/{provider}/authorization` | Start OAuth/authorization and return a short-lived authorization URL. |
| `GET` | `/integrations/callback/{provider}` | Provider OAuth callback; browser redirect, not called by frontend JavaScript. |
| `POST` | `/businesses/{business_id}/integrations` | Connect a provider using a supported secure setup method. |
| `GET` | `/businesses/{business_id}/integrations/{integration_id}` | Read non-secret connection details and health. |
| `POST` | `/businesses/{business_id}/integrations/{integration_id}/test` | Test provider connectivity and permissions. |
| `POST` | `/businesses/{business_id}/integrations/{integration_id}/sync` | Queue an initial or requested synchronization. |
| `DELETE` | `/businesses/{business_id}/integrations/{integration_id}` | Revoke/disconnect and schedule credential deletion. |

`provider` values include `woocommerce`, `telegram`, `paypal`, and later
`shopify`, `whatsapp`, and supported Meta channels. List and detail responses
include `id`, `provider`, `category`, `status`, `connected_at`,
`last_success_at`, `last_error`, `granted_scopes`, and sync status. Never return
access tokens, bot tokens, private keys, or OAuth client secrets.

Provider setup example:

```json
{
  "provider": "woocommerce",
  "credentials": {
    "store_url": "https://store.example",
    "consumer_key": "provided-over-tls",
    "consumer_secret": "provided-over-tls"
  }
}
```

Credential submission is allowed only over TLS to an authenticated,
business-authorized endpoint. Encrypt credentials at rest, redact them from
logs and traces, and never echo them in any response. Prefer OAuth/authorization
redirects when the provider supports them.

PayPal is limited to creating customer checkout sessions and verifying
customer payments. Reactant and the Business Agent must not read merchant
balances, create payouts, or transfer merchant funds.

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
| `GET` | `/businesses/{business_id}/owner-assistant/thread` | Get or create the single private owner thread and latest messages. |
| `GET` | `/businesses/{business_id}/owner-assistant/messages` | Paginate private thread messages. |
| `POST` | `/businesses/{business_id}/owner-assistant/messages` | Send an owner/team message to the business agent. |
| `POST` | `/businesses/{business_id}/owner-assistant/messages/{message_id}/read` | Mark a private agent message read. |

Owner send body:

```json
{
  "text": "For same-day dispatch, confirm with me before promising a time.",
  "client_message_id": "client-generated-uuid"
}
```

Use `client_message_id` or `Idempotency-Key` to make retries safe. The
response includes the persisted owner message and an accepted agent-run ID or
status. Do not claim the agent answered until an agent response message exists.

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
2. The response includes a random, one-use `ticket` with a short expiry (no
   more than 60 seconds) and a WebSocket URL.
3. Client opens the returned WebSocket URL. The server consumes the ticket,
   verifies its user and business membership, and authorizes event topics.
4. Reconnect by requesting a new ticket. Do not put long-lived bearer tokens
   in URLs or logs.

Client frame:

```json
{
  "type": "subscribe",
  "topics": ["owner_assistant", "approvals", "notifications"]
}
```

Server event:

```json
{
  "type": "owner_assistant.message_created",
  "business_id": "uuid",
  "occurred_at": "2026-11-04T17:00:00Z",
  "data": {
    "message": {
      "id": "uuid",
      "thread_id": "uuid",
      "kind": "clarification",
      "text": "Should the agent offer the item in the blue finish?",
      "created_at": "2026-11-04T17:00:00Z"
    }
  }
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
updates.

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
  approval decisions, and other retried side effects.
- Optional `X-Request-ID` for client correlation; server always returns
  `request_id`.
- Use `ETag`/`If-Match` for concurrent edits to business or agent settings.
  Return `412 Precondition Failed` for a stale version.

## 15. Frontend-to-endpoint mapping

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

## 16. Minimum implementation and acceptance checklist

- [ ] Implement all routes in sections 2-13 or explicitly mark a route
  `planned` in generated OpenAPI before frontend integration begins.
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
