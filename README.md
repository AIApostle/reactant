# Reactant

Reactant is an AI business operations platform for small businesses that sell
through messaging and online stores. It connects business data and customer
channels to a shared Business Agent, with the backend enforcing permissions,
pricing, inventory, and payment state.

## How it works

1. A business creates a catalog or connects its storefront.
2. It connects customer channels such as Telegram or website chat.
3. Customer messages are saved in Supabase and queued for the agent worker.
4. The Strands Agent SDK orchestrates the conversation and calls scoped
   business tools. Google Gemini provides model inference; the backend owns
   credentials and validates every tool operation.
5. For a purchase, the backend calculates the total, creates an AgentCard
   checkout, and sends the customer to PayPal-hosted checkout.
6. PayPal capture and webhooks are verified before an order is marked paid.
   The receipt worker then creates a receipt and sends payment updates to the
   customer and business owner.

Postgres is the source of truth. The web app is a React and TypeScript dashboard;
the API and workers use FastAPI, Supabase, and Python. Payment status must come
from verified PayPal results, never a browser redirect.

## Repository layout

- `backend/` — FastAPI API, Strands workers, integrations, and Supabase
  migrations.
- `frontend/app/` — React dashboard and public checkout pages.
- `Work/` — product requirements, architecture, API contract, setup guides,
  and integration notes.
- `backend/AGENTS.md` — backend-specific contribution instructions.

## GitHub checkout and local setup

Clone the repository:

```sh
git clone https://github.com/AIApostle/reactant.git
cd reactant
```

You need Python 3.11, [`uv`](https://docs.astral.sh/uv/), Node.js, and npm. The
backend and frontend run as separate processes.

In one terminal, configure and start the backend:

```sh
cd backend
uv sync
cp .env.example .env
# Edit .env with your Supabase project URL and publishable/anon key.
uv run uvicorn main:app --reload --port 8000
```

In another terminal, configure and start the frontend:

```sh
cd frontend/app
npm ci
cp .env.example .env.local
# Set VITE_API_BASE_URL=http://localhost:8000/api/v1, and enter the
# same Supabase project URL and its public key used by the backend.
npm run dev
```

The local frontend uses `http://localhost:8000/api/v1` for the API. Never put
PayPal secrets, Gemini keys, Supabase service keys, or encryption keys in
frontend variables or GitHub commits. Use the `.env.example` templates and
store real secrets in ignored local environment files or deployment secrets.
Database migrations are manual; review the setup guide before applying them.

## Deployment and integration setup

The hosted frontend is deployed on Vercel and the API on Render. The agent
worker can run as a separate Render Background Worker. Hosted services need
their own environment variables; local `.env` files do not deploy. PayPal
Sandbox setup requires the partner app credentials, seller onboarding, webhook
registration, and matching webhook ID mapping.

The current backend endpoint is `https://reactant-x0kv.onrender.com`. The
previous endpoint, `https://reactant.onrender.com`, is retained here for
rollback reference. Set `PUBLIC_API_BASE_URL` on the new Render service to the
current endpoint so newly configured integrations receive callback URLs on
the active service.

See the detailed guides:

- [Local and hosted setup](Work/setup.md)
- [Backend configuration](Work/backend-setup.md)
- [Frontend configuration](Work/frontend-setup.md)
- [AgentCard and PayPal setup](Work/agentcard-setup.md)
- [API contract](Work/api-contract.md)
- [Product requirements](Work/product-requirements.md)
- [Technical solution approach](Work/solution-approach.md)

## Important payment behavior

An accepted PayPal webhook only means the event was accepted for processing.
It does not by itself confirm payment. Reactant marks a transaction paid only
after PayPal confirms a matching completed capture. If checkout says payment is
processing, do not start another payment; use the AgentCard setup guide to
diagnose the PayPal event and capture status.
