import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.errors import AppError
from app.core.logging import logger
from app.db.indexes import create_indexes
from app.routers import admin, auth, payments, referrals, subscriptions, telegram_auth, wallet
from app.services.telegram_auth_service import register_webhook
from app.workers import oxapay_poller


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_indexes()
    await register_webhook()
    poller_task = asyncio.create_task(oxapay_poller.run_forever())
    logger.info("payment-backend startup complete")
    yield
    poller_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await poller_task


app = FastAPI(title="Payment Backend API", version="1.0.0", lifespan=lifespan)


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
