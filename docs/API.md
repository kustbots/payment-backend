# API Reference & Frontend Integration Guide

Base URL: `https://<your-deployment-host>` (locally: `http://localhost:8000`). Every route below is prefixed as shown. All request/response bodies are JSON. Interactive, always-up-to-date docs are also available at `/docs` (Swagger) and `/redoc` on any running instance.

## Contents

- [Auth model](#auth-model)
- [Errors](#errors)
- [Auth endpoints](#auth-endpoints)
- [Wallet endpoints](#wallet-endpoints)
- [Subscription endpoints](#subscription-endpoints)
- [Payment endpoints](#payment-endpoints)
- [Referral endpoints](#referral-endpoints)
- [Admin endpoints](#admin-endpoints)
- [Integration walkthroughs](#integration-walkthroughs)
- [Idempotency & double-spend protection](#idempotency--double-spend-protection-read-this)

---

## Auth model

This API uses its own email/password + JWT accounts — **independent of any other identity system**. There is no linked Telegram account, no OAuth.

1. `POST /api/auth/register` and `POST /api/auth/login` return an `access_token` and a `refresh_token`.
2. Send the access token on every authenticated request: `Authorization: Bearer <access_token>`.
3. Access tokens expire in ~30 minutes (`ACCESS_TOKEN_EXPIRE_MINUTES`). When one expires (you'll get a `401`), call `POST /api/auth/refresh` with the refresh token to get a new pair. Refresh tokens last ~14 days (`REFRESH_TOKEN_EXPIRE_DAYS`).
4. There is no logout/revocation endpoint in this version — tokens are valid until they expire. Don't build a "sign out everywhere" feature against this API yet; ask backend if you need it.

## Errors

All handled errors return `{"detail": "<human-readable message>"}` with an appropriate status code:

| Status | Meaning |
|---|---|
| 400 | Generic bad request |
| 401 | Missing/invalid/expired token, or wrong login credentials |
| 402 | Insufficient points balance |
| 403 | Authenticated, but not an admin (on admin-only routes) |
| 404 | Resource not found (unknown plan/package/subscription/user) |
| 409 | Conflict — e.g. already cancelled, duplicate purchase in flight |
| 422 | Request body failed validation (FastAPI's standard validation error shape applies here, not the `{"detail": string}` shape above) |

Standard FastAPI `422` validation errors (bad field types, missing required fields, regex mismatches) look like: `{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}`.

---

## Auth endpoints

### `POST /api/auth/register`
Public. Creates an account.

Request:
```json
{
  "email": "user@example.com",
  "password": "at-least-8-chars",
  "referral_code": "OPTIONAL8CHARCODE"
}
```
Response `201`:
```json
{
  "id": "665f1c2e...", "email": "user@example.com", "points": 0.0,
  "role": "user", "referral_code": "AB12CD34", "created_at": "2026-01-01T00:00:00"
}
```

### `POST /api/auth/login`
Public.
```json
{ "email": "user@example.com", "password": "..." }
```
Response `200`:
```json
{ "access_token": "...", "refresh_token": "...", "token_type": "bearer" }
```

### `POST /api/auth/refresh`
Public (bearer of a valid refresh token).
```json
{ "refresh_token": "..." }
```
Response `200`: same shape as login — a fresh access + refresh token pair.

---

## Wallet endpoints

Points are this app's internal currency. 1 point == 1 USD equivalent (matches the pricing tables below).

### `GET /api/wallet/balance` — auth required
```json
{ "points": 12.5 }
```

### `GET /api/wallet/bundles` — public
Returns the purchasable point bundles (crypto-only, no points-payment option for buying points):
```json
[
  {"key": "5", "label": "5 Points", "amount": 5.0, "points": 5},
  {"key": "10", "label": "10 Points", "amount": 9.5, "points": 10},
  {"key": "25", "label": "25 Points", "amount": 22.5, "points": 25},
  {"key": "50", "label": "50 Points", "amount": 42.5, "points": 50},
  {"key": "100", "label": "100 Points", "amount": 80.0, "points": 100}
]
```

### `POST /api/wallet/bundles/{package_key}/purchase` — auth required
Creates an OxaPay invoice for the given bundle (`package_key` is one of `5`, `10`, `25`, `50`, `100`). Response `200`:
```json
{
  "track_id": "1234567890",
  "pay_url": "https://pay.oxapay.com/...",
  "amount_usd": 9.5,
  "purpose": "points_bundle",
  "status": "pending",
  "created_at": "2026-01-01T00:00:00"
}
```
Redirect the user to `pay_url` (or render it as a QR code). Points are credited automatically once OxaPay confirms payment (webhook-driven — no client action needed). Poll `GET /api/payments/invoices/{track_id}` if you want to show a "waiting for payment..." status in your UI.

### `GET /api/wallet/transactions` — auth required
Paginated (most recent 200) ledger of everything that has touched the user's points balance: `points_purchase`, `bulk_points_credit`, `admin_grant`, `referral_credit`, `refund`, `crypto_invoice`.

---

## Subscription endpoints

### `GET /api/subscriptions/plans` — public
```json
[
  {"key": "2d", "label": "2 Days Weekend", "amount": 6.0, "hours": 48},
  {"key": "7d", "label": "1 Week", "amount": 15.0, "hours": 168},
  {"key": "30d", "label": "1 Month", "amount": 50.0, "hours": 720},
  {"key": "120d", "label": "3 Months (+1 Month Free)", "amount": 140.0, "hours": 2880}
]
```

### `GET /api/subscriptions/claimer-settings/options` — public
Valid values for the `api_claimer` product's optional `claimer_settings` (see below):
```json
{
  "currency_options": ["usdt", "btc", "eth", "ltc", "trx", "doge"],
  "drop_options": ["Daily1", "Daily2", "Daily3", "DailyOther", "HighRollers", "PlaySmarter", "WeeklyStream", "OtherDrops"]
}
```

### `POST /api/subscriptions/purchase/points` — auth required
Buys a plan using the user's points balance instead of crypto. **Requires an `Idempotency-Key` header** — see [Idempotency](#idempotency--double-spend-protection-read-this) below; generate a fresh random UUID per purchase *attempt* on the client (not per plan — a retried attempt after a network error must reuse the same key).

Headers: `Idempotency-Key: <client-generated-uuid>`

Request:
```json
{
  "product_type": "code_claimer",
  "plan_key": "2d",
  "stake_username": "someusername",
  "session_token": null,
  "claimer_settings": null
}
```
- `product_type`: `"code_claimer"` or `"api_claimer"`.
- `stake_username`: 3–51 chars, `[A-Za-z0-9_@]` only.
- `session_token`: required (≥ some length set by the external claimer service) only for `api_claimer` if you want a container deployed as part of this purchase; omit/`null` otherwise.
- `claimer_settings` (optional, `api_claimer` only): `{"currency": "usdt", "vault": true, "process_all": false, "drops": ["Daily1", "HighRollers"]}`. Any field can be omitted/`null` to use the deployer's default. `currency` must be one of, and `drops` must be a subset of, the values from `GET /api/subscriptions/claimer-settings/options` — invalid values return `422`.

Response `200` — the created subscription:
```json
{
  "id": "665f...", "product_type": "code_claimer", "plan_key": "2d", "status": "active",
  "stake_username": "someusername", "hours": 48, "amount_usd": 6.0,
  "started_at": "...", "expires_at": "...", "cancelled_at": null, "refund_amount": null,
  "app_name": null, "deploy_url": null, "deploy_status": null, "activation_failed": false,
  "claimer_settings": null
}
```
`activation_failed: true` means the points were spent and the subscription record was created, but the call to the external activation service failed — surface this to the user as "activated, contact support if issues persist" rather than a hard error, and flag it for backend/admin follow-up (see `POST /api/admin/subscriptions/{id}/extend` for remediation options).

Errors: `402` insufficient points, `404` unknown plan, `409` a purchase with this idempotency key is already mid-flight or already failed (message tells you which).

### `POST /api/subscriptions/purchase/crypto` — auth required
Same request body as above (including optional `claimer_settings`), minus `Idempotency-Key` (not needed — crypto purchases are deduplicated server-side by OxaPay `track_id` instead). Returns an invoice (same shape as the wallet bundle purchase response, `purpose: "plan_purchase"`). The subscription is created automatically once OxaPay confirms payment.

### `GET /api/subscriptions/me` — auth required
Returns an array of the caller's own subscriptions (all statuses), newest first.

### `POST /api/subscriptions/{id}/cancel` — auth required, must own the subscription
Cancels an active subscription and credits any refund (refund amount is `remaining_hours * refund_rate`; refund rates are currently configured to `0.0` by default — check with backend for current values). Returns the updated subscription (`status: "cancelled"`). Calling this twice on the same subscription returns `409` the second time — no double refund.

### `PATCH /api/subscriptions/{id}/settings` — auth required, must own the subscription
Updates currency/vault/process_all/drops on an **already-deployed** `api_claimer` container (pushes the change to the running container via the deployer, then persists it). Request body is the same optional `claimer_settings` shape shown above (send only the fields you want to change — omitted/`null` fields are left as-is). Returns the updated subscription.

Only works when the subscription is `status: "active"`, is `product_type: "api_claimer"`, and already has a deployed container — otherwise `409`. `404` if the subscription doesn't exist or isn't owned by the caller. `422` for invalid currency/drop values.

---

## Payment endpoints

### `POST /api/payments/oxapay/webhook`
**Not for frontend use.** This is OxaPay's server-to-server callback, configured via `OXAPAY_CALLBACK_URL`. It's HMAC-verified; calling it manually without a valid signature will `401`.

### `GET /api/payments/invoices/{track_id}` — auth required, must own the invoice
Poll this for payment status while a user is looking at a crypto payment screen:
```json
{ "track_id": "...", "purpose": "points_bundle", "amount_usd": 9.5, "status": "pending", "created_at": "..." }
```
`status` transitions `pending` → `paid` (fulfilled) or `pending` → `expired` (15 min timeout by default).

---

## Referral endpoints

### `GET /api/referrals/me` — auth required
```json
{ "referral_code": "AB12CD34", "referred_count": 3 }
```
Share `referral_code` with new users; they pass it as `referral_code` on `POST /api/auth/register`. When a referred user completes a **crypto** purchase (plan or points bundle), the referrer is automatically credited 10% of the paid amount as points. Points-paid purchases do **not** trigger a referral credit — this is intentional.

---

## Admin endpoints

All require the caller's account to have `role: "admin"` (403 otherwise). There's no self-service way to become an admin — see the main README's "Configuration" section.

- `POST /api/admin/users/{user_id}/grant-points` — body `{"amount": 10}` (negative to deduct). Returns the updated user.
- `GET /api/admin/users/{user_id}` — view a user's profile/balance.
- `POST /api/admin/subscriptions/{id}/extend` — body `{"hours": 24}` (1–8760). Extends an active subscription's expiry and re-calls the external activation API for the extra hours.
- `GET /api/admin/subscriptions?status=active&product_type=api_claimer` — list/filter all subscriptions (both filters optional).

---

## Integration walkthroughs

### A) New user signs up and buys points with crypto
1. `POST /api/auth/register` → `POST /api/auth/login` → store both tokens.
2. `GET /api/wallet/bundles` → show packages → user picks one.
3. `POST /api/wallet/bundles/{key}/purchase` → get `pay_url` → open it (redirect or embed) for the user to pay.
4. Poll `GET /api/payments/invoices/{track_id}` every few seconds, or just poll `GET /api/wallet/balance` — either will reflect the credit once OxaPay confirms (no action needed from your frontend beyond waiting/polling).

### B) Buy a subscription plan with points
1. `GET /api/subscriptions/plans` → user picks a plan.
2. `GET /api/wallet/balance` → confirm they have enough (optional client-side check — the server enforces this regardless).
3. Generate a UUID, send `POST /api/subscriptions/purchase/points` with `Idempotency-Key: <uuid>`.
4. On any network failure/timeout where you're not sure if the request landed, **retry with the exact same `Idempotency-Key`** — it's safe, the server will not double-charge and will return the original result.
5. On success, show the returned subscription; if `activation_failed: true`, show a "processing, contact support if this persists" state rather than an error.

### C) Buy a subscription plan with crypto
Same as (A) but call `POST /api/subscriptions/purchase/crypto` instead of the bundle endpoint, then poll for payment confirmation — the subscription appears in `GET /api/subscriptions/me` once paid.

---

## Idempotency & double-spend protection (read this)

This backend was specifically built to close race conditions that existed in a prior version of this product (concurrent requests double-spending points, duplicate payments being credited twice, etc). Two things frontend needs to know:

1. **Points purchases require an `Idempotency-Key` header.** Generate one UUID per purchase *attempt* (not per click — if you retry after a timeout/network error, reuse the same key). The server guarantees at-most-once processing per key: a retried request with the same key returns the original outcome instead of re-charging.
2. **You do not need to build any client-side "prevent double submit" locking for correctness** (disabling the buy button while a request is in flight is still good UX practice) — the server is the source of truth and cannot be double-charged even if your UI somehow fires the request twice.
