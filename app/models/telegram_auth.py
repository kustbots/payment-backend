from pydantic import BaseModel


class TelegramLoginStartResponse(BaseModel):
    token: str
    deep_link: str
    expires_in: int


class TelegramLoginStatusResponse(BaseModel):
    status: str  # "pending" | "completed" | "expired"
    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str | None = None
