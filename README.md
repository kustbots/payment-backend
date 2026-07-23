# payment-backend

A standalone FastAPI backend for subscription plans, a points wallet, and crypto payments (OxaPay). Built to replace a legacy Telegram bot with a web-callable API a frontend can integrate directly.

For the full HTTP API reference (every endpoint, request/response shapes, auth, error codes, and a step-by-step integration walkthrough), see **[docs/API.md](docs/API.md)**.

## Quick start (local dev)

Requirements: Python 3.11+, a MongoDB instance (Atlas or local).

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash; use .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
cp .env.example .env            # then fill in real values
uvicorn app.main:app --reload
```

The API is served at `http://localhost:8000`. Interactive OpenAPI docs are auto-generated at `http://localhost:8000/docs` (Swagger UI) and `http://localhost:8000/redoc`.

## Configuration

All configuration is via environment variables (see `.env.example` for the full list with comments). Never commit a real `.env` — it's gitignored.

Key ones frontend/infra teams should know about:

- `MONGO_URI` / `MONGO_DB_NAME` — this service owns its own database; it does **not** share data with any other system.
- `JWT_SECRET_KEY` — must be a long random secret in any real deployment.
- `OXAPAY_API_KEY`, `OXAPAY_CALLBACK_URL` — OxaPay merchant key and the public URL OxaPay should POST payment confirmations to (`/api/payments/oxapay/webhook`).
- `CLAIMER_API_URL`, `API_CLAIMER_AUTH_URL`, `CLAIMER_ADMIN_TOKEN`, `API_CLAIMER_DEPLOYERS` — the external product-fulfillment services this backend calls after a purchase is confirmed.
- `ADMIN_BOOTSTRAP_EMAIL` — the one email address that is auto-promoted to `role: "admin"` on registration. After that, promote further admins by setting `role: "admin"` directly on their user document in MongoDB.

## Running tests

```bash
pytest
```

Tests run against an in-memory mocked MongoDB (`mongomock-motor`) — no real database needed. `tests/test_wallet_atomicity.py`, `tests/test_purchase_idempotency.py`, and `tests/test_subscription_cancel.py` specifically exercise the concurrency/race-condition guarantees described in `docs/API.md`.

## Project layout

```
app/
├── main.py          FastAPI app, startup/shutdown, router wiring
├── core/            config, security (JWT/hashing), logging, error types
├── db/               MongoDB access + index setup
├── models/          Pydantic request/response schemas
├── deps/             auth dependencies (get_current_user / get_current_admin)
├── services/        business logic (the only layer that writes to MongoDB)
├── routers/         thin HTTP layer, one file per resource
└── workers/          OxaPay fallback poller (background asyncio task)
```
