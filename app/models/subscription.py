from datetime import datetime

from pydantic import BaseModel, Field


class ClaimerSettingsIn(BaseModel):
    """Deploy-time / manageable container settings for the api_claimer product.
    All fields optional -- None means "use the deployer's default"."""

    currency: str | None = None
    vault: bool | None = None
    process_all: bool | None = None
    drops: list[str] | None = None


class PurchaseWithPointsRequest(BaseModel):
    product_type: str = Field(pattern="^(code_claimer|api_claimer)$")
    plan_key: str = Field(pattern="^(2d|7d|30d|120d)$")
    stake_username: str = Field(min_length=3, max_length=51, pattern=r"^[A-Za-z0-9_@]{3,51}$")
    session_token: str | None = None
    claimer_settings: ClaimerSettingsIn | None = None


class PurchaseWithCryptoRequest(BaseModel):
    product_type: str = Field(pattern="^(code_claimer|api_claimer)$")
    plan_key: str = Field(pattern="^(2d|7d|30d|120d)$")
    stake_username: str = Field(min_length=3, max_length=51, pattern=r"^[A-Za-z0-9_@]{3,51}$")
    session_token: str | None = None
    claimer_settings: ClaimerSettingsIn | None = None


class SubscriptionOut(BaseModel):
    id: str
    product_type: str
    plan_key: str
    status: str
    stake_username: str
    hours: int
    amount_usd: float
    started_at: datetime
    expires_at: datetime
    cancelled_at: datetime | None = None
    refund_amount: float | None = None
    app_name: str | None = None
    deploy_url: str | None = None
    deploy_status: str | None = None
    deploy_progress: int | None = None
    deploy_message: str | None = None
    activation_failed: bool = False
    claimer_settings: dict | None = None

    @classmethod
    def from_mongo(cls, doc: dict) -> "SubscriptionOut":
        return cls(
            id=str(doc["_id"]),
            product_type=doc["product_type"],
            plan_key=doc["plan_key"],
            status=doc["status"],
            stake_username=doc["stake_username"],
            hours=doc["hours"],
            amount_usd=doc["amount_usd"],
            started_at=doc["started_at"],
            expires_at=doc["expires_at"],
            cancelled_at=doc.get("cancelled_at"),
            refund_amount=doc.get("refund_amount"),
            app_name=doc.get("app_name"),
            deploy_url=doc.get("deploy_url"),
            deploy_status=doc.get("deploy_status"),
            deploy_progress=doc.get("deploy_progress"),
            deploy_message=doc.get("deploy_message"),
            activation_failed=doc.get("activation_failed", False),
            claimer_settings=doc.get("claimer_settings"),
        )


class PlanOut(BaseModel):
    key: str
    label: str
    amount: float
    hours: int


class ClaimerSettingsOptionsOut(BaseModel):
    currency_options: list[str]
    drop_options: list[str]
