import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import logger
from app.db.indexes import create_indexes
from app.routers import admin, auth, payments, referrals, subscriptions, telegram_auth, wallet
from app.services.telegram_auth_service import register_webhook
from app.workers import oxapay_poller, subscription_expiry


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_indexes()
    await register_webhook()
    poller_task = asyncio.create_task(oxapay_poller.run_forever())
    expiry_task = asyncio.create_task(subscription_expiry.run_forever())
    logger.info("payment-backend startup complete")
    yield
    poller_task.cancel()
    expiry_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await poller_task
    with contextlib.suppress(asyncio.CancelledError):
        await expiry_task


app = FastAPI(title="Payment Backend API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def catch_unhandled_exceptions(request: Request, call_next):
    # A handler registered via @app.exception_handler(Exception) is wired into
    # Starlette's ServerErrorMiddleware, which sits OUTSIDE CORSMiddleware --
    # its response would never get CORS headers, so the browser blocks it
    # entirely (looks like a network failure, not a readable error). A plain
    # HTTP middleware runs INSIDE CORSMiddleware instead, so catching here
    # means CORS headers still get applied to the resulting error response.
    try:
        return await call_next(request)
    except Exception as exc:
        logger.exception(f"Unhandled exception on {request.method} {request.url.path}: {exc}")
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


app.include_router(auth.router)
app.include_router(telegram_auth.router)
app.include_router(wallet.router)
app.include_router(subscriptions.router)
app.include_router(payments.router)
app.include_router(referrals.router)
app.include_router(admin.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
