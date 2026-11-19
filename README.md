# Reactant

### Keep your business selling. Let AI handle the work behind every conversation.

Reactant is an AI-powered business operations platform that connects your business, sales channels, customers, and payment systems to intelligent AI agents.

From product discovery and customer conversations to orders, payments, and follow-ups, Reactant helps businesses manage the activities that keep sales moving.

Whether you're running a growing business or managing an established operation with multiple sales channels, Reactant gives your business an intelligent layer that connects its operations and helps it scale.

**One business. One shared intelligence. Connected everywhere your customers are.**

---

## The problem

Running a business increasingly means operating across multiple platforms.

Customers discover products on social media, ask questions through messaging apps, browse online stores, place orders through different channels, and pay through different payment providers.

Behind the scenes, businesses have to keep everything coordinated:

- Answering customer enquiries across multiple platforms.
- Keeping product information, prices, and inventory accurate.
- Managing orders and tracking their progress.
- Coordinating payments and confirming transactions.
- Following up with customers and handling support.
- Keeping business operations organized as sales grow.

As a business expands, these responsibilities become increasingly difficult to manage. More customers and more sales channels often mean more operational complexity.

Traditional tools help businesses manage individual parts of this process, but the connections between them are often left to people.

**Reactant is built to change that.**

## What is Reactant?

Reactant brings business operations and customer engagement into one connected system, powered by an AI Business Agent.

Rather than treating every communication channel or business tool as a separate system, Reactant connects them through a shared business intelligence layer.

The AI Business Agent understands the business, interacts with customers, accesses authorized business capabilities, and helps execute real business workflows.

It doesn't simply generate responses. It can retrieve products, check availability, assist with orders, and initiate payment workflows using tools provided by Reactant.

The backend remains responsible for validating business operations, enforcing permissions, and maintaining reliable records.

## What Reactant does

### 1. Shopify and WooCommerce integrations

Reactant integrates with **Shopify** and **WooCommerce** to connect businesses' existing online stores directly to their AI Business Agent. Rather than creating a separate storefront or maintaining a disconnected copy of a merchant's business, Reactant connects to the systems they already use to manage their commerce operations.

Using the **Shopify Admin API** and **WooCommerce REST API**, Reactant can access the store data and operational capabilities required to support the business through its AI agent.

The integrations cover more than product information. They provide access to key commerce resources, including:

- **Products and Variants:** Retrieve product details, descriptions, images, SKUs, categories, variations, and other product attributes.
- **Pricing and Inventory:** Access current product prices, stock levels, and availability so the agent can provide customers with accurate information.
- **Orders:** Retrieve and work with order information, including purchased items, customer details, totals, and order status.
- **Customers:** Access relevant customer records and order history where the merchant has granted the required permissions.
- **Order Management:** Support commerce workflows that allow the agent to assist customers with purchases and order-related enquiries.

#### How the integrations work

Each platform has its own connector within Reactant's backend.

For Shopify, merchants authorize Reactant to access their store through Shopify's app authentication process. Reactant uses the Shopify Admin API to communicate with the store on the merchant's behalf.

For WooCommerce, merchants connect their WordPress-powered store by authorizing Reactant to use the WooCommerce REST API. The integration uses the store's API credentials with the permissions required for the connected operations.

Once connected, Reactant retrieves the permitted store information and maps it into its internal commerce data model. This allows the AI Business Agent to work with a consistent representation of products, customers, inventory, and orders, regardless of which commerce platform a business uses.

Webhooks are used to receive relevant store events, such as product updates, inventory changes, and order activity. This helps Reactant keep its internal data synchronized with the merchant's actual store rather than depending entirely on repeated manual imports.

The AI Business Agent interacts with these systems through controlled backend tools. When a customer asks about a product, the agent can retrieve the relevant information from the connected store. When a customer wants to place an order, the agent can use the available commerce and checkout workflows. The backend remains responsible for validating operations and communicating with the external platform.

#### Why this matters

A business does not have to abandon Shopify or WooCommerce to use Reactant. It can continue managing its existing store while Reactant connects its commerce operations to customer conversations and AI-powered workflows.

This makes Reactant an operational layer on top of existing commerce infrastructure, helping businesses connect their stores, sales channels, customers, and AI agents without having to rebuild their entire commerce system.
### 2. A connected business catalog

Every business needs a reliable source of product information.

Reactant provides its own catalog for businesses that want to upload and manage their products directly. Businesses can add product images, descriptions, prices, variants, and other relevant information without needing to build an online store first.

Businesses that already operate online stores can connect their existing storefronts and bring product information into their Reactant workflows.

The catalog gives the AI Business Agent access to the information it needs to answer product enquiries and assist customers.

### 3. Customer conversations across channels

Customers should be able to reach a business through the platforms they already use.

Reactant is designed around a channel-independent communication architecture that connects customer conversations to the same business intelligence and operational systems.

As channel integrations expand, businesses can manage conversations from platforms such as:

- WhatsApp
- Instagram
- Facebook Messenger
- Telegram
- Business websites
- TikTok and other supported platforms

The goal is to give businesses a unified way to manage customer engagement without maintaining separate AI systems for every platform.

### 4. The AI Business Agent

At the centre of Reactant is a shared AI Business Agent.

It understands customer requests, retrieves relevant business information, and uses authorized tools to carry out business operations.

It can help with:

- Answering product and service enquiries.
- Recommending products based on customer needs.
- Checking product prices and availability.
- Helping customers select product variants.
- Assisting with order creation.
- Initiating payment workflows.
- Providing order and payment updates.
- Escalating conversations to human staff when necessary.

The agent operates within business-defined permissions and backend-enforced rules. It cannot independently invent product prices, stock availability, order status, or successful payment confirmations.

### 5. AgentCard: agent-initiated checkout

AgentCard connects customer conversations to payment workflows.

When a customer decides to purchase something, the AI Business Agent can initiate an AgentCard transaction through Reactant.

Reactant validates the order, calculates the amount, creates a checkout session, and directs the customer to the payment experience.

For the current PayPal integration, the customer completes payment through PayPal-hosted checkout.

Reactant verifies payment results through PayPal's APIs and webhooks before marking an order as paid.

Once payment is confirmed, Reactant can generate a receipt and communicate the transaction update to the customer and business.

### 6. Connected business operations

Reactant is designed to bring business capabilities together rather than operate as an isolated chatbot.

Its architecture supports integrations with:

- Online storefronts and commerce platforms.
- Messaging and communication channels.
- Payment providers.
- Business catalogs and inventory systems.
- Customer and conversation records.
- Other operational services.

As businesses grow, new channels, integrations, and workflows can be added without rebuilding the underlying AI Business Agent for each one.

## How Reactant works

Reactant connects customer-facing channels to a shared business intelligence and execution layer.

1. **Connect business data:** A business creates a Reactant catalog or connects an existing storefront.
2. **Connect customer channels:** The business connects supported communication channels.
3. **Receive conversations:** Incoming customer messages are received, stored, and queued for processing.
4. **Understand and respond:** The Strands Agents SDK orchestrates the Business Agent, while Google Gemini provides model inference.
5. **Execute business operations:** The agent calls scoped Reactant tools to retrieve information and perform authorized operations.
6. **Complete purchases:** Reactant validates orders, calculates totals, creates AgentCard checkout sessions, and initiates payment workflows.
7. **Verify and update:** Payment providers supply authoritative transaction results. Reactant verifies these results before updating order and payment records.
8. **Keep everyone informed:** Customers and business owners receive relevant updates, and receipts can be generated after successful payment confirmation.

## Built for businesses that grow

Reactant is not limited to a particular business size, industry, or sales channel.

A business can begin with a simple product catalog and a single customer communication channel. As it grows, it can connect additional storefronts, communication platforms, payment services, and operational workflows.

The objective is to provide a foundation that can support increasing customer interactions and increasingly complex business operations.

Reactant is being designed to accommodate that growth through:

- A shared business intelligence layer.
- Modular integrations and channel connectors.
- Centralized business and customer records.
- Permission-controlled AI tools.
- Backend-enforced business rules.
- Extensible payment and order workflows.
- A scalable API and worker architecture.

The vision is simple: businesses should not have to rebuild their operational systems every time they grow or adopt another platform.

## Technology and architecture

Reactant combines AI orchestration, backend-controlled business tools, and integrated services.

| Layer | Technology | Responsibility |
|---|---|---|
| Frontend | React, TypeScript, Vite | Business dashboard, website chat integration, and checkout interface |
| Frontend UI | Radix Themes, AG Grid Community and AG Grid React | UI components and data tables for the inbox, catalog, and orders |
| Backend API | Python, FastAPI | Business logic, APIs and integrations |
| Agent orchestration | Strands Agents SDK | Agent workflows and tool orchestration |
| Model inference | Google Gemini | Understanding and generating responses |
| Database | Supabase PostgreSQL | Persistent business and transaction records |
| Authentication | Supabase Auth | User authentication |
| Storage | Supabase Storage | Product images and other business media |
| Commerce integrations | Shopify Admin REST API and WooCommerce REST API v3 | Store authorization, connection checks, and product synchronization |
| Payments | PayPal REST APIs and verified PayPal webhooks | Checkout, capture, refund, and payment events |
| Deployment | Vercel and Render | Frontend, API and background workers |

### Where to find integrations and UI libraries in the code

| Feature | Implementation |
|---|---|
| Shopify and WooCommerce connector requests and product normalization | [`backend/src/integrations/storefronts.py`](backend/src/integrations/storefronts.py) |
| Integration authorization, credentials, connection checks, and product sync routes | [`backend/src/integrations/routes.py`](backend/src/integrations/routes.py) |
| PayPal seller connection UI and Website Chat developer-docs link | [`frontend/app/src/App.tsx`](frontend/app/src/App.tsx) |
| Customer checkout UI and PayPal return/cancel handling | [`frontend/app/src/AgentCardCheckout.tsx`](frontend/app/src/AgentCardCheckout.tsx) |
| PayPal API authentication, order creation, capture, refunds, and response validation | [`backend/src/agentcard/paypal.py`](backend/src/agentcard/paypal.py) |
| AgentCard checkout, payment, refund, and verified transaction routes | [`backend/src/agentcard/routes.py`](backend/src/agentcard/routes.py) |
| PayPal webhook endpoint and signature verification | [`backend/src/webhooks/routes.py`](backend/src/webhooks/routes.py) |
| Receipt generation and delivery after payment verification | [`backend/src/agentcard/receipts.py`](backend/src/agentcard/receipts.py) |
| AG Grid tables for the catalog, inbox, and orders | [`frontend/app/src/App.tsx`](frontend/app/src/App.tsx), [`frontend/app/package.json`](frontend/app/package.json) |
| Optional APIMatic portal URL and OpenAPI-spec URL settings | [`frontend/app/.env.example`](frontend/app/.env.example) |

AG Grid is used by the React app for its catalog, conversation inbox, and order tables. The **Developer docs** link is shown in the Website Chat integration and opens the configured `VITE_APIMATIC_PORTAL_URL`; when that is unset, it falls back to `VITE_OPENAPI_SPEC_URL` or the API's `/openapi.json` document. APIMatic is an optional external documentation portal link; the application does not use APIMatic as a runtime service or generate SDKs from it in this repository.

### Architectural principles

**Postgres as the source of truth:** Business data, orders, conversations, and transaction records are maintained in persistent storage.

**Backend-controlled execution:** AI agents interact with business systems through scoped tools. They do not directly access provider credentials or bypass backend validation.

**Reliable payment verification:** Browser redirects and customer messages are not proof of payment. Reactant relies on verified payment-provider results.

**Modular integrations:** Communication channels and external services connect through reusable integration interfaces.

**Business-controlled automation:** Business owners retain control over permissions, operational rules, and human intervention.

**Separation of intelligence and execution:** The AI interprets requests and selects tools. Reactant's backend validates and executes operations.

## Repository structure

```text
reactant/
├── backend/
│   ├── API
│   ├── agents/
│   ├── integrations/
│   ├── workers/
│   └── migrations/
│
├── frontend/
│   └── app/
│       ├── dashboard/
│       ├── components/
│       └── public-checkout/
│
├── Work/
│   ├── setup.md
│   ├── backend-setup.md
│   ├── frontend-setup.md
│   ├── agentcard-setup.md
│   ├── api-contract.md
│   ├── product-requirements.md
│   └── solution-approach.md
│
└── README.md
```

The backend also contains `backend/AGENTS.md`, which provides backend-specific contribution instructions.

## Getting started

### Requirements

- Python 3.11
- [uv](https://docs.astral.sh/uv/)
- Node.js
- npm
- A Supabase project

You will also need the appropriate API credentials for the integrations you intend to run.

### 1. Clone the repository

```bash
git clone https://github.com/AIApostle/reactant.git
cd reactant
```

### 2. Configure the backend

```bash
cd backend
uv sync
cp .env.example .env
```

Configure your local environment with the required Supabase project URL and public key, along with any additional backend integration credentials.

Start the API:

```bash
uv run uvicorn main:app --reload --port 8000
```

### 3. Configure the frontend

Open another terminal:

```bash
cd frontend/app
npm ci
cp .env.example .env.local
```

Configure the frontend environment:

```env
VITE_API_BASE_URL=http://localhost:8000/api/v1
```

Add the same Supabase project URL and public key used by the application.

Start the frontend:

```bash
npm run dev
```

The frontend and backend run independently.

### 4. Configure integrations

Follow the relevant setup documentation before enabling external services.

- [Local and hosted setup](Work/setup.md)
- [Backend configuration](Work/backend-setup.md)
- [Frontend configuration](Work/frontend-setup.md)
- [AgentCard and PayPal setup](Work/agentcard-setup.md)
- [API contract](Work/api-contract.md)

Database migrations should be reviewed and applied manually according to the setup guide.

## Deployment

Reactant's current deployment architecture uses:

- **Vercel:** Frontend application.
- **Render:** Backend API.
- **Render Background Worker:** Asynchronous agent and background processing.
- **Supabase:** Database, authentication, and storage.

Each hosted service requires its own environment configuration. Local environment files are not automatically deployed.

Never commit secrets or expose private API credentials in frontend variables.

## Payment security

Payment integrity is a fundamental part of Reactant.

The application must never treat a browser redirect, frontend callback, screenshot, or customer message as proof of payment.

A payment is marked as successful only after Reactant verifies a matching completed capture with the payment provider.

Webhook events are authenticated, processed idempotently, and reconciled with provider-side transaction information.

An accepted webhook event alone does not establish that payment has completed.

If a checkout is still processing, customers should not initiate another payment. The transaction should first be reconciled using its existing checkout and payment references.

See [AgentCard and PayPal setup](Work/agentcard-setup.md) for implementation and troubleshooting details.

## Project direction

Reactant is being developed toward a broader vision of connected business operations.

Areas of continued development include:

- Expanding messaging and social platform integrations.
- Improving unified customer conversations and inbox management.
- Expanding agent capabilities and business workflows.
- Supporting more payment providers and checkout methods.
- Introducing voice-based AI business receptionists.
- Improving business automation, analytics, and operational controls.
- Supporting increasingly complex businesses and multi-channel operations.

The long-term goal is to make Reactant an intelligent operational layer that helps businesses manage and grow their operations across the platforms where they sell and serve customers.

---

**Reactant — Your business, connected.**
