import json
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class DeployerConfig(BaseSettings):
    deploy_id: int
    url: str
    token: str
    limit: int = 100


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Mongo
    MONGO_URI: str
    MONGO_DB_NAME: str = "payments_app"

    # JWT
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14

    # OxaPay
    OXAPAY_API_KEY: str = ""
    OXAPAY_API_BASE: str = "https://api.oxapay.com"
    OXAPAY_CALLBACK_URL: str = ""

    # External Rebate Claimer activation API
    CLAIMER_API_URL: str = ""
    CLAIMER_ADMIN_TOKEN: str = ""
    API_CLAIMER_AUTH_URL: str = ""

    # Deployer pool (JSON string in env)
    API_CLAIMER_DEPLOYERS: str = "[]"
    API_CLAIMER_MIRROR_SITE: str = ""
    API_CLAIMER_REGION: str = "eu"

    # Refunds / payments
    REFUND_RATE_CLAIMER_PER_HOUR: float = 0.0
    REFUND_RATE_API_CLAIMER_PER_HOUR: float = 0.0
    PAYMENT_TIMEOUT_SECONDS: int = 900
    POLL_INTERVAL_SECONDS: int = 30

    # App
    ENV: str = "development"
    ADMIN_BOOTSTRAP_EMAIL: str = ""

    @property
    def deployers(self) -> list[dict]:
        try:
            return json.loads(self.API_CLAIMER_DEPLOYERS)
        except (json.JSONDecodeError, TypeError):
            return []

    @property
    def is_production(self) -> bool:
        return self.ENV.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
