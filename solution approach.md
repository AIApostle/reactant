# Reactant — Technical Solution Approach

**Version:** 1.0  
**Date:** 03 November 2026  
**Status:** Working engineering specification

## 1. Recommended implementation strategy

Build Reactant as a modular monolith first. Keep domain modules and connector
interfaces cleanly separated, but deploy a small number of services rather
than introducing microservices prematurely. PostgreSQL remains the source of
truth. Background workers handle synchronization, media processing, webhook
retries, and other asynchronous work.

The first release should implement one complete vertical slice:
**manual product catalog + WooCommerce sync + connected customer channel +
Business Agent + cart/order + PayPal**. This supports both sellers with an
existing store and sellers who sell through chat without a dedicated
storefront.

| Stage | Deliverable | Exit condition |
|---|---|---|
| 1. Foundation | Auth, business tenancy, database, secrets, logs, dashboard shell. | Merchant can create a secure business workspace. |
| 2. Product catalog | Manual product entry and photo uploads, plus WooCommerce catalog import and reconciliation. | A seller without a store can create agent-ready products; synced products retain source and freshness metadata. |
| 3. Messaging | Telegram connector, webhook receiver, outbound messages, media handling. | Messages reliably enter and leave the correct business channel. |
| 4. Agent runtime | Context builder, tool registry, policy checks, tool execution, audit. | Agent answers catalog questions using actual store data. |
| 5. Commerce | Cart/order state machine and PayPal checkout/verification. | Test purchase reaches verified paid state without duplicate side effects. |
| 6. Operations | Customer inbox, private Agent messages, approvals, health, monitoring, and error recovery. | Merchant can supervise, respond to agent questions, decide approvals, and diagnose failures. |
| 7. Expansion | Shopify, WhatsApp, Instagram/Messenger, website chat. | New connectors reuse existing domain and agent interfaces. |

## 2. High-level architecture

The architecture separates customer channels, agent reasoning, business tools,
integration adapters, and deterministic commerce operations.

```text
Customer channels
  Telegram | WhatsApp | Instagram | Messenger | Website chat
                           |
                           v
                Channel Gateway / Webhooks
                           |
                           v
            Conversation + Message Service
                           |
                           v
                 Business Agent Runtime
              Context / LLM / Tool selection
                           |
                           v
                  Business Tool Registry
             Schema / policy / permissions
                /          |           \
               v           v            v
       Store Connectors  Commerce Engine  Media Service
       WooCommerce/      Cart/Order       Inbound/Outbound
       Shopify                |               |
               v             v               v
            Store APIs   Payment Module  Object Storage
                              |
                         PayPal etc.
                \             |            /
                 +------------+-----------+
                              |
                    PostgreSQL / Events
                              |
                    Background Jobs/Workers
                              |
              Workspace Dashboard / Audit
                 /                    \
       Customer Inbox          Private Owner Thread
                 |                    |
     Customer Channel APIs     Owner Assistant Service
```

The LLM is not a privileged integration client. It receives limited tools and
structured context. The backend owns credentials, tenant authorization,
validation, side effects, and persistence.

The private owner thread uses its own API, records, authorization checks, and
realtime topic. It never passes through customer conversation delivery.

## 3. Core components and responsibilities

| Component | Responsibilities |
|---|---|
| Frontend dashboard | Merchant onboarding, integration settings, agent configuration, customer inbox, private Agent messages, manual and synced catalog, orders, and status. |
| FastAPI application | API routes, webhook endpoints, domain services, authorization, and orchestration. |
| Channel gateway | Normalize inbound events, validate provider requests, resolve business/channel, and dispatch messages. |
| Conversation service | Persist customer messages, conversation state, assignments, customer links, and channel metadata. |
| Owner assistant service | Persist private agent/owner messages, enforce workspace membership, link approval records, and publish owner-only events. |
| Business Agent runtime | Assemble customer or owner-thread context, call the LLM, handle tool requests, enforce turn limits, and route output to the matching channel. |
| Tool registry | Define typed tools, schemas, permission requirements, validation, and execution handlers. |
| Store connectors | Normalize product, variant, inventory, order, and customer operations across storefront providers. |
| Product catalog | Store owner-managed products and imported products in a unified searchable model with explicit source, availability, agent access, and image assets. |
| Commerce Engine | Own carts, order validation, totals, order state transitions, and checkout initiation. |
| Payment module | Create payment requests, verify provider evidence, process callbacks, and reconcile payment state. |
| Media service | Retrieve, validate, store, transform, and deliver images/files across provider APIs. |
| Policy/approval engine | Evaluate action risk, enforce merchant configuration, and hold actions for approval. |
| Workers and event processor | Run sync jobs, process webhooks, retry transient failures, and reconcile external state. |
| PostgreSQL | Authoritative application state, tenancy, messages, commerce records, audit, and event records. |
| Object storage | Private storage for media and operational artifacts. |

## 4. Agent execution model

Use a controlled tool-calling runtime. A provider-agnostic LLM interface can
support the selected model provider. The initial implementation does not
require training a custom model.

1. Receive and normalize a customer message or an authorized owner message.
2. Resolve its business and channel. Customer messages resolve to customer,
   provider, and conversation; owner messages resolve only to the private owner
   thread. Verify tenant boundaries and channel-specific permissions.
3. Load relevant business profile, agent instructions, policies, the matching
   channel's history, and trusted context. Never mix owner messages into a
   customer transcript or customer context.
4. Provide the LLM with the message and tools permitted for that channel and
   business.
5. Validate each requested tool name and argument against a strict schema.
6. Check ownership, permissions, action risk, approval rules, and required data
   freshness.
7. Execute through a domain service and connector; never pass raw provider
   credentials to the model.
8. Return a compact typed result to the model and allow a bounded number of
   additional tool calls.
9. Generate a response for the originating channel. An owner question, status,
   or approval request is persisted to the private owner thread; a customer
   answer is sent through its customer channel adapter.
10. Persist the trace and publish only to the matching channel's authorized
    realtime topic.

Set limits for maximum tool calls, execution time, token usage, and retries.
Tool handlers should be deterministic, observable, and independently
testable.

### Initial agent tool catalogue

| Tool | Purpose | Class |
|---|---|---|
| `search_products` | Search business catalog by query/category. | Read |
| `get_product` | Retrieve authoritative product details. | Read |
| `get_product_variants` | Retrieve available variants/options. | Read |
| `check_inventory` | Check available stock for product/variant. | Read |
| `get_product_images` | Return approved product photos for customer-channel delivery. | Read |
| `search_faq` | Retrieve approved business FAQ content. | Read |
| `get_business_policy` | Retrieve delivery, returns, payment, or other policy. | Read |
| `request_human_handoff` | Assign or flag conversation for staff. | Operational |
| `create_cart` | Create or retrieve a customer cart. | Write |
| `add_cart_item` | Add a validated product/variant/quantity. | Write |
| `get_cart` | Retrieve cart contents and totals. | Read |
| `validate_cart` | Recheck price, stock, and cart rules. | Validation |
| `create_order` | Create an order from a validated cart. | Sensitive write |
| `create_checkout` | Create a PayPal customer checkout session for an eligible, server-validated order when the merchant has enabled this permission. | Sensitive write |
| `get_order_status` | Retrieve current order state. | Read |
| `send_product_image` | Send a selected real catalog image. | External side effect |
| `request_action_approval` | Create a pending approval request. | Control |
| `request_owner_input` | Ask a business owner a question or notify them of an exception in the private owner thread. | Owner-channel control |

Do not expose arbitrary SQL, shell commands, unrestricted HTTP requests, or
general-purpose credential access as agent tools. Add tools only when a clear
use case, permission model, and failure behavior are defined. Agent-created
owner messages must use a service-only command, never the browser API or a
customer messaging adapter. Approval requests reference the canonical approval
record; a chat message itself does not authorize an action. Product search and
detail tools exclude archived or agent-disabled products. Unknown stock is
represented as unknown, never as confirmed availability.

## 5. End-to-end solution workflow

**Connect → Synchronize → Understand → Act → Transact → Verify → Respond**

1. **Connect:** Merchant authorizes Reactant to access a store, channel, or
   payment provider. Credentials are validated and stored securely. The
   integration record captures provider, scopes, status, and connection
   metadata.
2. **Synchronize:** A merchant can enter products and upload images directly
   when no storefront exists. Connected storefronts import catalog and
   operational data. Webhooks provide change notifications; scheduled
   reconciliation catches missed events. Records track source, provider
   identifiers, and last-synced timestamps.
3. **Understand:** Inbound messages are normalized. The runtime loads business
   settings, relevant catalog/policy data, conversation history, and safe
   customer context.
4. **Reason and act:** The model selects from allowed tools. Backend
   validation checks schemas, tenant, permissions, business rules, freshness,
   and approval requirements.
5. **Transact:** Commerce services validate the cart, calculate totals, create
   an order, and ask the payment adapter to initialize checkout.
6. **Verify:** Payment callbacks are authenticated and reconciled with
   provider APIs. Order/payment state changes only after trusted verification.
7. **Respond and learn:** The channel adapter sends the response. Events, tool
   traces, outcomes, and failures are recorded for audit, support, and
   analytics.

## 6. Integration approach

### 6.1 WooCommerce — first storefront connector

- Use WooCommerce REST API v3 over HTTPS for products, variations, inventory,
  orders, and supported customer operations.
- For onboarding, evaluate WooCommerce application authorization; otherwise
  provide secure API-key setup with clear permission explanation.
- Use least privilege compatible with the workflow. Store Consumer
  Key/Secret encrypted and never expose them to the browser or LLM.
- Register webhooks for product/order changes; validate signatures and
  deduplicate deliveries.
- Run scheduled reconciliation because webhooks can be delayed, duplicated,
  or missed.
- Track external IDs and synchronization timestamps; preserve provider data
  needed for troubleshooting.

References: [WooCommerce REST API](https://woocommerce.com/document/woocommerce-rest-api/),
[developer REST API](https://developer.woocommerce.com/docs/apis/rest-api/),
[webhooks](https://woocommerce.com/document/webhooks/).

### 6.2 Shopify — next storefront connector

- Build a Shopify app authorization flow with explicit scopes and merchant
  consent.
- Use the current GraphQL Admin API for supported operations; do not design a
  new integration around the legacy REST Admin API.
- Use offline access where background synchronization is required and manage
  token lifecycle securely.
- Subscribe to relevant webhooks and reconcile state periodically.
- Map Shopify objects into Reactant's provider-neutral product/order model.

References: [Shopify app authentication](https://shopify.dev/docs/apps/build/authentication-authorization),
[Shopify APIs](https://shopify.dev/docs/apps/build/apis),
[GraphQL Admin API](https://shopify.dev/docs/api/admin-graphql).

### 6.3 Telegram — first messaging connector

- Merchant creates a bot through `@BotFather` and supplies the bot token
  during onboarding.
- Reactant calls `getMe` to validate the token and identify the bot.
- Reactant configures a webhook with a secret token and maps the bot/channel
  to a business.
- Inbound updates are validated, normalized, persisted, and dispatched to the
  Business Agent.
- Outbound text and media use Telegram Bot API methods such as `sendMessage`
  and `sendPhoto`.
- The bot is a separate business identity; it does not take over the
  merchant's personal Telegram account.

Reference: [Telegram Bot API](https://core.telegram.org/bots/api).

### 6.4 WhatsApp, Instagram, Messenger, and website chat

Implement these as separate channel adapters after the first workflow is
stable. Each platform has its own account setup, permissions, webhook
verification, messaging windows, template rules, media behavior, and review
requirements. Messaging permissions do not automatically grant advertising or
publishing permissions.

- **WhatsApp:** Use the WhatsApp Business Platform / Cloud API and follow
  current verification, template, and messaging policies.
- **Instagram:** Target eligible professional accounts and current supported
  messaging APIs and permissions.
- **Facebook Messenger:** Connect eligible Pages and use supported Page
  messaging permissions.
- **Website chat:** Create a Reactant widget with a signed business/channel
  identifier and controlled browser-to-backend connection.

### 6.5 Payment provider abstraction

Keep payments in a dedicated module. The agent can request checkout creation,
but Commerce and Payment modules own amount calculation, order references,
provider requests, verification, and state transitions.

Use PayPal as the first payment provider. A provider interface should allow
another provider to be added without changing agent tools or order-domain
logic. The agent may create a PayPal checkout session only for a
server-validated customer order when the merchant has enabled the permission.
The policy engine checks approval settings and any configured order-total
threshold before execution. It must not be able to access merchant balances,
make payouts, or move merchant funds.

```text
PaymentProvider
  initialize_checkout(order, customer, return_url) -> CheckoutSession
  verify_transaction(reference) -> VerifiedPayment
  parse_webhook(headers, body) -> ProviderEvent
  refund(payment, amount) -> RefundResult  # later, permission-gated
```

A browser redirect is not proof of payment. Verify webhook authenticity and
transaction status with PayPal. Match provider reference, amount, currency,
and internal order reference before marking an order paid.

The checkout permission is scoped to customer purchases. The backend must
revalidate price, stock, currency, order ownership, and order state immediately
before creating checkout, enforce idempotency, and audit the request and its
approval decision. Approval thresholds apply to the authoritative order total,
not an amount supplied by the agent or browser.

Reference: [PayPal Checkout](https://developer.paypal.com/docs/checkout/).

## 7. Media and image handling

Media should be provider-independent. A channel adapter translates
provider-specific media references into a normalized internal representation.

| Direction | Processing flow |
|---|---|
| Inbound image | Receive provider media ID/reference → retrieve bytes using provider API → validate size/type → store privately → attach to message → optionally pass to a vision-capable model. |
| Outbound product image | Agent selects product/image ID from trusted catalog results → backend retrieves actual asset → validates channel constraints → sends using provider media API → records delivery result. |

- Do not let the model invent or synthesize a product image and present it as
  the merchant's actual catalog image.
- Use private object storage and short-lived signed URLs where appropriate.
- Validate MIME type and actual file signature; enforce size limits and
  malware scanning where suitable.
- Respect provider-specific image formats, dimensions, file-size limits, and
  media download lifetimes.
- Telegram commonly uses `getFile` for retrieval and `sendPhoto` for outbound
  images; WhatsApp uses media IDs and Graph API media endpoints.

## 8. Data model and multi-tenancy

The following is a logical starting model, not a final migration
specification. Use UUID primary keys internally and store provider IDs
separately.

| Entity | Purpose / key fields |
|---|---|
| `users` | Authenticated people linked to Supabase Auth identity. |
| `businesses` | Tenant/workspace; name, slug, timezone, currency (USD by default; ISO 4217), status. |
| `business_members` | User-to-business membership, role, invitation state. |
| `business_settings` | Profile, operating hours, policies, support details. |
| `integrations` | Provider, business ID, status, scopes, external account ID, sync metadata. |
| `integration_credentials` | Encrypted provider secrets/tokens; strict service-only access. |
| `channels` | Channel type, provider account/bot ID, integration link, status. |
| `customers` | Business-scoped customer identity and provider identity mappings. |
| `conversations` | Business, channel, customer, status, assignment, timestamps. |
| `messages` | Customer conversation, direction, content, provider message ID, delivery state. |
| `owner_assistant_threads` / `owner_assistant_messages` | Private business-owner thread and messages, stored separately from customer conversations. |
| `media_assets` | Storage key, MIME type, size, checksum, provider metadata, access policy. |
| `products` / `variants` | Normalized manual or provider-synced product data, source/external IDs, price, optional stock, availability, agent access, and freshness. |
| `product_media` | Ordered links between products and validated media assets used for agent retrieval and channel delivery. |
| `carts` / `cart_items` | Customer cart, product/variant, quantity, validated price snapshot. |
| `orders` / `order_items` | Internal order, line items, totals, currency, provider references, state. |
| `payments` | Provider, reference, amount, currency, status, verification metadata. |
| `agent_configs` | Instructions, model settings, enabled tools, tone, handoff rules. |
| `tool_permissions` | Business allow/deny rules, thresholds, approval requirements. |
| `approval_requests` | Action, payload summary, requester, approver, status, timestamps. |
| `agent_runs` / `tool_calls` | Execution trace, model/provider metadata, redacted arguments/results. |
| `business_events` | Append-oriented domain event log for analytics and audit. |
| `webhook_events` | Provider, event ID, signature result, processing state, deduplication key. |
| `usage_records` | Usage and billing metering. |

Every tenant-owned record should include `business_id` or be reachable only
through a tenant-owned parent. Enforce membership and tenant checks in backend
services and PostgreSQL Row Level Security (RLS). Background jobs must carry
explicit business context.

## 9. API and event design

Use REST/HTTP for dashboard and integration management, webhooks for provider
events, and WebSockets or a realtime service for live inbox updates. Normalize
external payloads at the edge before passing them into domain services.
Use a separate owner-only realtime topic for private agent/owner messages.
Manual and provider-synced products share a tenant-scoped catalog API, with
source-specific update rules. Upload binary image data directly to private
object storage using short-lived signed upload URLs; the API issues and verifies
those uploads before products can reference them.

Representative endpoints:

```text
POST   /api/v1/businesses
GET    /api/v1/businesses/{business_id}
GET    /api/v1/businesses/{business_id}/products
POST   /api/v1/businesses/{business_id}/products
GET    /api/v1/businesses/{business_id}/products/{product_id}
PATCH  /api/v1/businesses/{business_id}/products/{product_id}
DELETE /api/v1/businesses/{business_id}/products/{product_id}
POST   /api/v1/businesses/{business_id}/media/uploads
POST   /api/v1/businesses/{business_id}/media/{asset_id}/complete
POST   /api/v1/integrations/woocommerce/connect
POST   /api/v1/integrations/telegram/connect
GET    /api/v1/integrations
POST   /api/v1/agent/config
GET    /api/v1/conversations
GET    /api/v1/conversations/{conversation_id}
POST   /api/v1/conversations/{conversation_id}/messages
POST   /api/v1/conversations/{conversation_id}/handoff
GET    /api/v1/businesses/{business_id}/owner-assistant/thread
GET    /api/v1/businesses/{business_id}/owner-assistant/messages
POST   /api/v1/businesses/{business_id}/owner-assistant/messages
POST   /api/v1/businesses/{business_id}/owner-assistant/messages/{message_id}/read
GET    /api/v1/orders
GET    /api/v1/orders/{order_id}
GET    /api/v1/approvals
POST   /api/v1/approvals/{approval_id}/decision
POST   /internal/v1/businesses/{business_id}/owner-assistant/messages
POST   /webhooks/telegram/{channel_id}
POST   /webhooks/woocommerce/{integration_id}
POST   /webhooks/paypal/{integration_id}
```

The `/internal/v1` owner-message command is restricted to the agent runtime
service identity. It is not a browser route and does not accept normal user
bearer tokens.

Representative events:

- `message.received`, `message.sent`, `message.delivery_failed`
- `owner_assistant.message_created`, `owner_assistant.message_read`
- `catalog.sync_started`, `catalog.sync_completed`, `catalog.sync_failed`
- `product.updated`, `inventory.updated`
- `agent.run_started`, `agent.run_completed`, `agent.run_failed`
- `tool.call_requested`, `tool.call_succeeded`, `tool.call_failed`
- `approval.requested`, `approval.approved`, `approval.rejected`
- `cart.created`, `cart.updated`, `order.created`, `order.updated`
- `checkout.initiated`, `payment.succeeded`, `payment.failed`
- `human_handoff.requested`, `human_handoff.accepted`

Webhook processing should be asynchronous where possible: authenticate and
persist the event quickly, acknowledge the provider, then process it through a
worker. Use provider event IDs or deterministic deduplication keys.

## 10. Order and payment state management

Represent commerce operations with explicit state machines rather than loosely
coupled booleans.

| Entity | Example states |
|---|---|
| Cart | `active` → `validated` → `converted_to_order`; or `expired` / `abandoned`. |
| Order | `draft` → `pending_payment` → `paid` → `processing` → `fulfilled`; with `cancelled` / `refunded` / `failed` branches. |
| Payment | `created` → `pending` → `succeeded` / `failed` / `expired`; with `refunded` / `partially_refunded` where supported. |
| Approval | `pending` → `approved` / `rejected` / `expired` / `cancelled`. |

Transitions must be validated by domain services. Record who or what initiated
each transition, source event, and timestamp. Use idempotency keys for
checkout and order-creation requests.

## 11. Security, privacy, and governance

- **Authentication:** Use Supabase Auth or equivalent managed identity;
  validate JWTs server-side.
- **Authorization:** Enforce business membership and role checks on every
  business-scoped endpoint and background action.
- **Channel isolation:** Keep owner-assistant data separate from customer
  conversations in storage, access policies, search, realtime topics, and
  provider delivery. Protect internal agent commands with service identity.
- **RLS:** Enable PostgreSQL Row Level Security for tenant-owned tables and
  test policies with multiple tenants.
- **Secrets:** Encrypt integration credentials at rest; restrict decryption to
  backend services; rotate/revoke credentials when disconnected.
- **LLM boundary:** Never include API keys, access tokens, signing secrets, or
  unnecessary personal data in prompts.
- **Tool security:** Strict schemas, allowlists, tenant checks, permission
  checks, action limits, and approval gates.
- **Webhook security:** Verify signatures or secret tokens, reject invalid
  requests, deduplicate, and log verification outcomes.
- **Data minimization:** Collect only information needed; define retention and
  deletion policies.
- **Audit:** Record sensitive actions and approval decisions; redact secrets
  and unnecessary personal data from logs.
- **Human control:** Provide agent disable switch, integration revocation, and
  conversation takeover.
- **Owner-channel privacy:** Keep agent-to-owner messages and realtime events
  private to authorized workspace members; never deliver them to customers.
- **Abuse protection:** Rate limits, request-size limits, bot protection, and
  anomaly monitoring.

## 12. Reliability and background processing

- Use a durable job queue for catalog sync, media retrieval, webhook
  processing, scheduled reconciliation, and retryable provider calls. Redis
  with Celery, RQ, or an equivalent worker system is a practical starting
  point.
- Acknowledge provider webhooks after durable receipt, not after a
  long-running agent response.
- Retry transient network and rate-limit failures with exponential backoff and
  jitter.
- Do not retry permanent validation/authentication failures indefinitely.
- Use dead-letter handling or a failed-job queue for manual inspection.
- Make jobs idempotent and safe to replay.
- Track integration health, last successful sync, webhook lag, job age, and
  error rate.
- Use timeouts and circuit-breaker behavior for unhealthy external providers.

## 13. Recommended technology stack

| Layer | Recommendation | Reason |
|---|---|---|
| Web app | React + TypeScript | Productive dashboard ecosystem and strong typing. |
| API/backend | Python + FastAPI | Clear API layer and suitable Python ecosystem for agent orchestration. |
| Database | Supabase PostgreSQL | Relational source of truth, managed database, RLS, and operational tooling. |
| Authentication | Supabase Auth | Managed identity and JWT integration. |
| Storage | Supabase Storage or S3-compatible storage | Private media storage and scalable file handling. |
| Realtime | Supabase Realtime or WebSockets | Inbox updates and operational status. |
| Agent runtime | Controlled tool-calling runtime with provider adapter | Keeps execution, permissions, and observability under Reactant's control. |
| Background jobs | Redis + Celery/RQ or equivalent | Durable asynchronous integration work. |
| Payments | PayPal first; provider adapter | Customer checkout with provider-verified payment state. |
| Store integrations | WooCommerce first, Shopify next | Prove commerce workflow before broad integration scope. |
| Messaging | Telegram first, then WhatsApp and Meta channels | Fast initial end-to-end proof. |
| Hosting | Render or equivalent managed hosting | Simple deployment for the initial modular monolith. |
| Monitoring | Sentry + structured logs | Error reporting and traceability. |

Avoid premature microservices and Kubernetes. Split deployment units only
when scaling, reliability, team ownership, or operational isolation justifies
the complexity.

## 14. Suggested repository structure

```text
reactant/
├── apps/
│   ├── web/                       # React merchant dashboard
│   └── api/                       # FastAPI application entrypoint
├── backend/
│   ├── core/                      # config, security, database, tenancy
│   ├── modules/
│   │   ├── businesses/  ├── members/       ├── integrations/
│   │   ├── channels/    ├── conversations/ ├── messaging/
│   │   ├── media/       ├── products/      ├── agent/
│   │   ├── tools/       ├── commerce/      ├── payments/
│   │   ├── approvals/   ├── owner_assistant/ ├── events/     └── billing/
│   ├── connectors/
│   │   ├── stores/      # base, woocommerce, shopify
│   │   ├── messaging/   # base, telegram, whatsapp, instagram
│   │   ├── payments/    # base, paypal, future providers
│   │   └── ai/          # base and model-provider adapters
│   ├── workers/
│   └── tests/
├── packages/
│   ├── shared-types/
│   └── ui/
├── supabase/
│   ├── migrations/
│   └── seed.sql
├── docs/
│   ├── PRD.md
│   ├── SOLUTION_APPROACH.md
│   ├── API.md
│   ├── SECURITY.md
│   └── INTEGRATIONS.md
├── docker-compose.yml
├── README.md
└── .env.example
```

## 15. Testing and quality strategy

| Test level | What to test |
|---|---|
| Unit | Tool schemas, pricing/totals, state transitions, permission decisions, webhook signature verification, normalization. |
| Connector contract | Provider adapter behavior against mocked API responses and error conditions. |
| Integration | Database, queue, storage, webhook receiver, and provider sandbox interactions. |
| Agent evaluation | Grounded answers, correct tool choice, refusal when data is missing, safe handling of ambiguous requests. |
| Security | Tenant isolation, RLS, role enforcement, secret redaction, webhook forgery, prompt injection via untrusted content, upload content validation, and private media access. |
| End-to-end | Seller adds a product and photo without a storefront, connects a customer channel, and confirms the agent can answer from that product and share its image. Also test the WooCommerce-synced path through customer order and verified payment. |
| Resilience | Duplicate webhooks, delayed responses, timeouts, retries, worker restart, and provider downtime. |

Create a test business and test catalog with known products, variants, prices,
stock states, and images. Use payment sandbox mode until the full verification
and reconciliation path is proven.

## 16. Delivery roadmap

| Phase | Focus | Expected outcome |
|---|---|---|
| 0 — Design foundation | Confirm domain model, threat model, UX flows, API contracts, provider account requirements. | Implementation-ready architecture and backlog. |
| 1 — Platform foundation | Auth, tenancy, database migrations, business workspace, secrets, dashboard shell. | Secure merchant workspace. |
| 2 — Product catalog | Owner-managed products and photo uploads, plus WooCommerce import, webhooks, and reconciliation. | A seller without a store can create agent-ready products; synced products retain their source. |
| 3 — Telegram + agent | Bot connection, webhooks, conversations, runtime, tool registry, media. | Customer can ask questions and receive grounded answers/images. |
| 4 — Commerce + PayPal | Cart, order, checkout initialization, webhook verification, order updates. | End-to-end test transaction. |
| 5 — Merchant operations | Inbox, human handoff, approvals, monitoring, error handling, audit. | Merchant can supervise live operation. |
| 6 — Expansion | Shopify, WhatsApp, Meta messaging, website chat, analytics. | Broader channel and storefront coverage. |

## 17. Key implementation decisions

| Decision | Recommended direction |
|---|---|
| Architecture | Modular monolith first; clean module boundaries and connector interfaces. |
| Source of truth | Storefront for synced products and stock; Reactant catalog for owner-managed product facts; payment provider for payment evidence; Reactant DB for internal workflow state. |
| Agent topology | One logical Business Agent per business, shared across its channels. |
| AI responsibility | Reasoning and tool selection only; backend owns permissions, validation, and side effects. |
| First storefront | WooCommerce. |
| First channel | Telegram. |
| First payment provider | PayPal. |
| Database | PostgreSQL via Supabase. |
| Customer Personal Agents | Not part of MVP. |
| Marketing automation | Later phase; campaign publishing/spend actions approval-gated. |
| Analytics | Capture events from day one; build deeper reporting after the core workflow. |

## 18. Open decisions to resolve during implementation

- Whether WooCommerce onboarding uses its application authorization flow from
  day one or begins with merchant-generated API credentials.
- Exact role matrix for owner, admin, staff, and read-only members.
- Which order system is authoritative for each workflow: WooCommerce order
  creation, Reactant-native order orchestration, or a hybrid. Avoid conflicting
  duplicate orders.
- Whether customer identity is initially channel-specific or includes
  optional verified cross-channel linking.
- Retention periods for messages, media, agent traces, and personal data.
- Exact model provider, model selection, token budgets, and fallback behavior.
- Which agent actions require approval by default and what thresholds
  merchants can configure.
- Initial shipping/tax calculation responsibilities and how these are
  delegated to the connected storefront.

## 19. Technical references

- [WooCommerce REST API](https://woocommerce.com/document/woocommerce-rest-api/)
- [WooCommerce developer REST API](https://developer.woocommerce.com/docs/apis/rest-api/)
- [WooCommerce webhooks](https://woocommerce.com/document/webhooks/)
- [Shopify app authentication](https://shopify.dev/docs/apps/build/authentication-authorization)
- [Shopify APIs](https://shopify.dev/docs/apps/build/apis)
- [Shopify GraphQL Admin API](https://shopify.dev/docs/api/admin-graphql)
- [Telegram Bot API](https://core.telegram.org/bots/api)
- [PayPal Checkout](https://developer.paypal.com/docs/checkout/)
- [Supabase documentation](https://supabase.com/docs)
- [FastAPI documentation](https://fastapi.tiangolo.com/)

## Conclusion

Reactant should be built around a simple but important promise: connect a
business's existing systems, then give it one AI agent that can help operate
real workflows safely. The product succeeds when the agent does more than
produce convincing text: it retrieves accurate information, performs
permitted actions, verifies outcomes, and knows when to involve a human.

The recommended path is deliberately narrow at first. Prove WooCommerce +
Telegram + PayPal end to end, make the workflow reliable and observable, and
then expand the same architecture to more storefronts, channels, and
operational capabilities.
