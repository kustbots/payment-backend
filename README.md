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
- `TELEGRAM_AUTH_BOT_TOKEN` / `TELEGRAM_AUTH_BOT_USERNAME` — a bot created via [@BotFather](https://t.me/BotFather), used for the passwordless "log in with Telegram" flow (see `docs/API.md`). `TELEGRAM_WEBHOOK_BASE_URL` must be this app's own public URL so the app can register itself with Telegram at startup; `TELEGRAM_WEBHOOK_SECRET` is a random string you pick, used to verify incoming Telegram webhook calls are genuine. Leaving these blank simply disables Telegram login (email/password keeps working).
- `CORS_ALLOWED_ORIGINS` — comma-separated list of frontend origins allowed to call this API from a browser (e.g. `https://your-frontend.workers.dev`). Defaults to `*` (any origin) — tighten this once you know your frontend's real domain.

## Deploying (Koyeb / Render)

The app is a standard ASGI service — it just needs `MONGO_URI` pointing at a reachable MongoDB (e.g. Atlas) and the other secrets from `.env.example` set as platform env vars. A `Dockerfile` is included and works on both platforms; `Procfile` and `render.yaml` are provided for Render's native (non-Docker) Python runtime.

**Render:**
- Easiest: push this repo, then in Render choose "New > Blueprint" and point it at this repo — `render.yaml` defines the service, health check (`/health`), and the full env var list (secrets are marked `sync: false` so you fill them in in the dashboard, never in the file).
- Manual alternative: "New > Web Service", runtime "Python 3", build command `pip install -r requirements.txt`, start command from `Procfile` (`uvicorn app.main:app --host 0.0.0.0 --port $PORT`), health check path `/health`.

**Koyeb:**
- Create a service from this repo/branch; Koyeb auto-detects the `Dockerfile` and builds/runs it (it already binds to `$PORT`, which Koyeb injects).
- Set every variable from `.env.example` under the service's environment variables. Set the health check path to `/health`.

Either platform: set `ENV=production` so the dev-only `/api/payments/dev/mark-paid/{track_id}` endpoint is not registered, and point `OXAPAY_CALLBACK_URL` at that deployment's public URL + `/api/payments/oxapay/webhook`.

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
