# Reactant — Product Requirements Document

**Version:** 1.0  
**Date:** 03 November 2026  
**Status:** Working product specification

## Executive summary

Reactant is an AI-powered business operations platform for small and growing
businesses that sell through messaging channels, social posts, or an online
store. Businesses can connect a storefront or create a private product catalog
in Reactant by uploading photos and entering product details. They then connect
their customer communication channels and deploy one shared AI Business Agent.

The agent answers product questions using trusted catalog and policy data,
checks inventory, shares actual product images, helps customers build carts,
and initiates order and checkout workflows. Reactant is distinguished from a
generic chatbot by its connection to real business systems and its controlled,
verifiable operations, with clear permissions and human oversight.
Owners can supervise the agent through a private workspace channel for
questions, approvals, exceptions, and status updates, separate from customer
conversations.

The Reactant catalog is not a public storefront. It gives the business and its
agent one place to keep product photos, prices, descriptions, categories, and
optional stock information. The agent can use products the owner has made
available to it when answering customer questions and sharing product photos
in connected channels.

The MVP proves one complete workflow for either seller type: connect a
WooCommerce store or add products to the Reactant catalog, connect a Telegram
bot, answer customer questions from approved product data, share product
images, create an order, initiate PayPal checkout, verify payment, and update
the order.

## 1. Product overview

- **Product:** Reactant
- **Category:** AI-powered business operations and commerce automation
- **Primary customer:** Small and growing businesses that sell through
  messaging channels, social posts, or an online storefront.
- **Default currency:** USD; businesses can select another supported currency
  in their profile.
- **Positioning:** Connect your business channels and systems. Deploy an AI
  agent that helps operate your business across them.

| Pillar | Meaning | Examples |
|---|---|---|
| Connect | Bring existing business systems into Reactant or add product details directly. | WooCommerce, owner-managed catalog, Telegram, WhatsApp, Instagram, website chat |
| Operate | Give one shared Business Agent controlled access to business tools and approved product information. | Answer questions, find products, check stock when tracked, hand off to staff |
| Transact | Turn customer conversations into verified commerce workflows. | Cart, order, checkout, payment verification, order updates |
| Supervise | Keep the owner informed and in control without mixing internal discussion into customer threads. | Private agent messages, approvals, exceptions, owner guidance |
| Understand | Make operational activity measurable and useful. | Conversation trends, conversions, channel performance, agent quality |

## 2. Problem statement

Businesses often manage sales and customer support across disconnected tools:
product information lives in a storefront, conversations happen in messaging
apps, payments are handled by a provider, and staff move information between
them manually.

Many small sellers promote products through WhatsApp statuses, group posts, and
social channels without maintaining a dedicated website or online store. Their
product photos, prices, and details are scattered across posts and chat history,
so an agent has no reliable product source to search or share.

This leads to:

- Delayed answers to basic product, price, availability, and delivery questions.
- Unanswered customer inquiries that can become lost sales when owners are
  busy or away from their business.
- Repeated copying of product and order information between systems.
- Fragmented customer context across messaging channels.
- Generic AI answers that may not reflect actual stock, prices, or order state.
- Manual order and payment setup even when a conversation signals clear buying
  intent.
- Limited visibility into which inquiries become sales and where customers
  abandon the process.

Reactant connects a controlled AI agent to a business's actual systems and
provides a reliable way to perform approved operations.

## 3. Product vision and objectives

**Vision:** Make capable, reliable AI business operations accessible to
businesses without requiring them to build or replace an online storefront or
change the channels where their customers already talk to them.

Objectives:

- Reduce response time for common customer inquiries.
- Reduce missed sales opportunities caused by unanswered customer messages.
- Ground answers in live or recently synchronized business data.
- Let sellers without a storefront create an agent-ready catalog from their
  product photos and business-provided details.
- Convert more qualified conversations into carts, orders, and completed
  payments.
- Give merchants control over agent permissions, spending limits, approval
  thresholds, and human handoff.
- Provide consistent business context across connected channels.
- Make it possible to add stores, channels, and payment providers without
  rewriting the agent.

## 4. Target users and jobs to be done

| User | Needs and jobs |
|---|---|
| Business owner / merchant | Connect systems or add products manually, configure the agent, define policies, approve sensitive actions, monitor activity, and understand performance. |
| Social-commerce seller | Sell through WhatsApp statuses, groups, or other messaging/social channels without an online store; keep product photos and details ready for the agent to use. |
| Sales or support staff | See conversations, take over when needed, review order context, and resolve exceptions. |
| Customer | Ask questions naturally, discover relevant products, see accurate details and images, place an order, and receive clear updates. |
| Reactant administrator | Support onboarding, diagnose integration failures, monitor platform health, manage abuse, and resolve account issues. |

## 5. Product principles

1. **One agent, shared context:** Each business has one logical Business Agent
   across its connected channels.
2. **Business data remains authoritative:** A connected storefront is
   authoritative for synchronized products and stock. For owner-managed
   products, the merchant-maintained Reactant catalog is the source. Payment
   providers are authoritative for payment status.
3. **AI reasons; software executes:** The model selects from controlled tools;
   backend services validate requests and perform operations.
4. **No fabricated business facts:** Prices, stock, order status, and payment
   status come from trusted systems.
5. **Human control:** Merchants define permissions, approval thresholds,
   spending limits, and handoff rules.
6. **Incremental delivery:** Prove one end-to-end workflow before adding every
   integration.
7. **Provider independence:** Use adapters and stable internal interfaces to
   avoid hard-coupling the product to one vendor.

## 6. Product scope

### 6.1 MVP — must have

- Merchant registration, login, business workspace, and basic business
  settings.
- One WooCommerce store connection with securely stored credentials.
- Import and synchronization of products, variants, prices, stock,
  descriptions, and product images.
- A private business catalog where a seller without an online store can upload
  product photos, enter names, prices, categories, descriptions, and optional
  stock quantities, then choose which products the agent can use and share.
- A catalog that supports both manually managed products and products
  synchronized from connected storefronts, with a clear source indicator.
- One Telegram bot connection, with webhook-based message receipt and sending.
- One shared Business Agent with business-specific instructions, policies, and
  conversation context.
- A private Agent-to-Owner conversation for agent questions, approvals,
  exceptions, and status updates, separate from customer conversations and
  customer-facing channels.
- Controlled tools for product search and details, variants, inventory, image
  retrieval, FAQ/policy lookup, and human handoff.
- Conversation inbox with message history and human takeover.
- Basic cart and order workflow plus PayPal checkout initiation.
- Payment verification through provider webhooks and/or provider API before an
  order is marked paid.
- Merchant dashboard for integrations, agent settings, conversations, orders,
  approvals, and operational status.
- Audit trail for agent runs, tool calls, approvals, and important commerce
  events.

### 6.2 Next releases

- Shopify connector using the current app authorization approach and GraphQL
  Admin API.
- WhatsApp Business Platform / Cloud API.
- Instagram professional account and Facebook Messenger integrations, subject
  to platform permissions and messaging rules.
- Website chat widget.
- More advanced customer profiles and consent-based cross-channel identity
  resolution.
- Additional payment providers and delivery/shipping integrations.
- Operational analytics and AI-generated insights grounded in verified event
  data.

### 6.3 Out of scope for initial MVP

- Customer Personal Agents or a consumer agent marketplace.
- A fully autonomous agent with unrestricted access to merchant accounts.
- Autonomous ad spending, campaign publishing, or social media posting.
- A complete CRM replacement or accounting system.
- A custom-trained foundation model.
- Microservices, Kubernetes, or complex distributed infrastructure before
  scale requires them.
- A broad agent-to-agent commerce network; consider it only after the core
  merchant workflow is reliable.

## 7. Functional requirements

| ID | Requirement | Expected behavior |
|---|---|---|
| FR-01 | Business workspace | A user can create a business workspace and invite team members with roles. |
| FR-02 | Store connection | A merchant can connect a WooCommerce store and test the connection. |
| FR-03 | Catalog synchronization | Reactant imports products, variants, prices, inventory, descriptions, and image references. |
| FR-04 | Catalog freshness | Webhooks and scheduled reconciliation keep local data reasonably current. |
| FR-05 | Channel connection | A merchant can connect a Telegram bot and validate that it can send and receive messages. |
| FR-06 | Shared agent | All connected channels route to the same business-level agent configuration and context. |
| FR-07 | Grounded answers | The agent retrieves product and policy facts from trusted tools rather than guessing. |
| FR-08 | Product media | The agent can send actual catalog images supported by the channel. |
| FR-09 | Human handoff | A customer or agent can request staff assistance; the conversation enters a human-owned state. |
| FR-10 | Cart and order | The agent can help build a cart and request order creation through validated backend operations. |
| FR-11 | Customer checkout | When permitted by the merchant, the agent can create a PayPal-hosted checkout session for a backend-validated customer order. |
| FR-12 | Payment verification | Only verified provider evidence can transition an order to paid. |
| FR-13 | Approvals | Sensitive actions can require merchant approval before execution. |
| FR-14 | Auditability | Important agent actions, tool calls, approvals, and commerce state changes are recorded. |
| FR-15 | Failure handling | Integration/provider failures are surfaced without falsely claiming an action succeeded. |
| FR-16 | Private owner channel | The agent and authorized business members can exchange questions, answers, approvals, exceptions, and status updates in a private workspace thread. |
| FR-17 | Channel separation | Owner-agent messages are never merged into customer transcripts or delivered to customer messaging providers. |
| FR-18 | Manual product catalog | A merchant can create and manage products in Reactant without connecting an online storefront. |
| FR-19 | Product photos and details | A merchant can upload product photos and maintain the product name, price, category, description, and optional stock quantity. |
| FR-20 | Agent product access | A merchant can make a product available or unavailable to the agent. The agent can retrieve approved details and supported product photos for customer conversations. |
| FR-21 | Catalog source and availability | Manual and storefront-synchronized products have identifiable sources. The agent distinguishes tracked stock from unknown stock and does not invent availability. |

## 8. Key user journeys

### 8.1 Merchant onboarding

1. Merchant creates an account and business workspace.
2. Merchant enters business information, operating hours, support details, and
   policies.
3. Merchant connects a WooCommerce store. Reactant validates the credentials
   and imports catalog data.
4. Merchant configures the Business Agent's tone, instructions, allowed
   actions, and handoff rules.
5. Merchant creates a Telegram bot through BotFather, provides its token, and
   connects it.
6. Reactant validates the bot, configures its webhook, and runs a test
   message.
7. Merchant reviews setup status and enables the agent.

### 8.2 Customer product inquiry

1. Customer sends a message to the business's Telegram bot.
2. Reactant receives and validates the webhook, resolves the business and
   conversation, and stores the message.
3. The agent runtime loads relevant business settings, conversation history,
   and customer context.
4. The agent calls product search or product detail tools.
5. The backend queries synchronized catalog data and, when needed, checks the
   connected store for fresh information.
6. The agent responds with grounded product information and may send the
   actual product image.
7. The interaction and tool results are recorded for audit and analytics.

### 8.3 Order and payment

1. Customer indicates purchase intent.
2. Agent gathers product variant, quantity, and required customer details.
3. Backend validates availability and price before cart/order creation.
4. Commerce Engine creates an order with a stable internal identifier and
   external storefront reference when applicable.
5. Payment module creates a PayPal checkout request for the validated amount
   and order reference.
6. Customer completes payment on the provider's hosted checkout.
7. Reactant receives a provider webhook, verifies its signature, and
   independently verifies transaction status with the provider API where
   appropriate.
8. Only after verification does Reactant mark payment successful and update
   the order.
9. Customer and merchant receive the appropriate update.

### 8.4 Agent and owner communication

1. Agent work runs independently of the customer-facing conversation channel.
2. When business context is missing, a sensitive action needs approval, or an
   exception needs attention, the agent creates a message in the private
   Agent-to-Owner thread.
3. The owner reviews the request in Agent messages, responds with guidance, or
   approves/rejects the linked approval record.
4. The backend validates authorization and current business/order state before
   acting on a response or approval.
5. Resulting status returns to the private thread. Customer replies are sent
   only through the customer conversation workflow.

This channel is a workspace feature, not a new customer messaging integration.
Agent messages remain private to authorized workspace members and the agent
runtime.

### 8.5 Seller-managed catalog and product questions

1. A seller who has no online store opens Catalog and adds a product with one
   or more photos, a name, price, and details customers commonly ask about.
2. The seller may add a category and stock quantity. Leaving stock blank means
   availability is not tracked, not that the item is automatically in stock.
3. The seller chooses whether the agent may use the product information and
   share its photos.
4. A customer asks about an item in a connected messaging channel. The agent
   searches eligible catalog products, uses the verified business-provided
   details, and shares a relevant photo when the channel supports it.
5. If a detail is missing, stock is unknown, or the requested product is not
   found, the agent asks the owner or offers human assistance instead of
   guessing.

The catalog is an internal product source for agent-assisted selling. It does
not create a public shop, product page, or customer self-checkout site.

## 9. Business rules and acceptance expectations

- The agent must not claim an item is in stock unless trusted store data or a
  seller-maintained stock quantity supports it. An untracked quantity is
  unknown.
- The agent must not invent prices, discounts, variants, shipping fees, or
  delivery promises.
- Backend recalculates totals and validates quantities; it never trusts totals
  generated by the LLM or frontend.
- An order must not be marked paid based only on a customer message, browser
  redirect, or unverified webhook payload.
- Every external action is associated with a business, agent run, and
  traceable request.
- Retries must not create duplicate orders, charges, or messages; use
  idempotency keys where supported.
- If an integration is unavailable, the agent explains that it cannot verify
  the information and offers human assistance.
- The merchant can disable the agent or revoke an integration.
- Agent PayPal access is limited to creating customer checkout sessions for
  validated orders and checking payment status. It cannot access merchant
  balances, initiate payouts, or transfer funds.
- Merchants can disable agent-created checkout links and require approval for
  checkout actions, including above a configured order-total threshold.

## 10. Dashboard and UX requirements

| Area | Core content |
|---|---|
| Overview | Agent status, connected channels/stores, recent activity, orders, alerts, and setup progress. |
| Integrations | Connect/disconnect providers; show permissions, health, last sync, and errors. |
| Agent settings | Business profile, tone, instructions, policies, allowed tools, approval rules, operating hours, and handoff behavior. |
| Agent messages | Private agent-to-owner thread for clarifications, approvals, exceptions, and status updates. Clearly separate it from the customer inbox. |
| Inbox | Unified conversations, channel indicator, customer/order context, assignment, human takeover, and internal notes. |
| Catalog | Manually added and storefront-synced products, source, photos, details, price, optional stock, agent access, and sync status. Make clear this is not an online storefront. |
| Orders | Order status, line items, totals, payment state, provider reference, and event history. |
| Approvals | Pending actions, reason, payload summary, approve/reject controls, and audit history. |
| Settings | Business members, roles, security, billing, and data controls. |

Keep the first dashboard focused on setup, agent operation, conversations, and
orders. Avoid overwhelming merchants with advanced analytics before the core
workflow is proven.

## 11. Success metrics

| Metric | Definition / purpose |
|---|---|
| Time to first successful connection | Time from account creation to a working store or channel connection. |
| Time to first agent-ready product | Time from workspace creation to the first approved product being available to the agent, manually added or store-synced. |
| Time to first agent response | Time from incoming customer message to first agent response. |
| Unanswered inquiry rate | Share of customer conversations that remain without a timely response. |
| Grounded answer rate | Share of product/policy answers supported by successful trusted retrieval. |
| Tool success rate | Share of valid tool calls that complete successfully. |
| Human handoff rate | Share of conversations requiring staff intervention; interpret alongside resolution quality. |
| Conversation-to-cart rate | Share of eligible conversations that result in a cart. |
| Checkout initiation rate | Share of created carts/orders that reach checkout. |
| Verified payment conversion | Share of checkout attempts resulting in provider-verified payment. |
| Integration reliability | Webhook processing success, sync freshness, and connector error rates. |
| Merchant retention | Whether merchants continue using Reactant and keep the agent enabled. |

## 12. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Stale catalog or inventory | Webhooks, scheduled reconciliation, freshness metadata, and live checks for high-impact actions. |
| Hallucinated business facts | Tool-grounded responses, structured outputs, validation, and explicit uncertainty handling. |
| Duplicate orders/payments | Idempotency, unique references, transaction state machines, and retry-safe jobs. |
| Provider API changes | Adapter interfaces, version monitoring, integration tests, and staged rollouts. |
| Credential exposure | Encrypted secrets, least privilege, strict access controls, and no secrets in prompts/logs. |
| Unsafe or unauthorized product media | Validate file type, signature, and size; store images privately; scope access to the owning business and permitted agent/channel actions. |
| Out-of-date seller-managed product details | Make the merchant responsible for manual product facts; distinguish unknown stock from available stock and support quick edits or archive. |
| Cross-tenant leakage | Tenant scoping, database RLS, authorization checks, and isolation tests. |
| Owner/customer channel leakage | Separate message storage, authorization, realtime topics, search, and provider delivery; test that private owner messages never reach customers. |
| Unwanted autonomous action | Tool allowlists, approval gates, action limits, and kill switch. |
| Messaging policy violations | Follow each platform's current permissions, templates, messaging windows, and content rules. |

## MVP acceptance checklist

- [ ] A merchant can register, log in, create a business, and manage its
  workspace.
- [ ] A merchant can connect WooCommerce without exposing credentials to the
  frontend or model.
- [ ] Reactant imports products, variants, prices, stock, and images and shows
  sync health.
- [ ] A merchant can choose either to connect a store or start with a
  Reactant-managed catalog. Store connection is not required to add products.
- [ ] A seller without an online store can add a product with a photo, name,
  price, and customer-facing details.
- [ ] The seller can optionally track stock and choose whether the agent may
  use a product and share its photos.
- [ ] The agent retrieves and shares only eligible products from the manual or
  synced catalog, and does not treat unknown stock as confirmed availability.
- [ ] Catalog upload or product changes do not publish a public storefront.
- [ ] A merchant can connect Telegram and send/receive a test message.
- [ ] A customer message routes to the correct business and conversation.
- [ ] The Business Agent searches the catalog and answers using retrieved
  facts.
- [ ] The agent sends an actual product image from the connected catalog.
- [ ] The agent can initiate human handoff.
- [ ] A customer can build a cart and create an order with server-validated
  totals.
- [ ] Reactant initializes PayPal checkout in sandbox mode.
- [ ] A merchant can enable or disable agent-created customer checkout links
  and configure approval requirements and thresholds.
- [ ] Checkout is created only for an eligible, backend-validated order after
  current price and stock checks. The agent cannot initiate payouts or move
  merchant funds.
- [ ] Payment status changes only after verified provider evidence.
- [ ] Duplicate webhook deliveries do not create duplicate orders or payments.
- [ ] Tenant isolation tests prove one business cannot access another
  business's data.
- [ ] Merchant can disable the agent and revoke integrations.
- [ ] Agent runs, tool calls, approvals, and commerce state transitions are
  auditable.
- [ ] A business owner can exchange private messages with the agent and review
  linked approval requests without exposing that thread to customers.
- [ ] Customer channel messages and owner-agent messages remain separate in
  storage, authorization, realtime delivery, search, and provider sends.
- [ ] An owner can respond to a clarification request and decide a linked
  approval, with the backend returning the authoritative result.
