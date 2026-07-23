from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    referral_code: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: str
    email: EmailStr
    points: float
    role: str
    referral_code: str
    created_at: datetime


class UserInDB(BaseModel):
    id: str
    email: EmailStr
    hashed_password: str
    points: float
    role: str
    referral_code: str
    referrer_id: str | None
    created_at: datetime
    is_active: bool

    @classmethod
    def from_mongo(cls, doc: dict) -> "UserInDB":
        return cls(
            id=str(doc["_id"]),
            email=doc["email"],
            hashed_password=doc["hashed_password"],
            points=doc.get("points", 0.0),
            role=doc.get("role", "user"),
            referral_code=doc["referral_code"],
            referrer_id=str(doc["referrer_id"]) if doc.get("referrer_id") else None,
            created_at=doc["created_at"],
            is_active=doc.get("is_active", True),
        )

    def to_out(self) -> UserOut:
        return UserOut(
            id=self.id,
            email=self.email,
            points=self.points,
            role=self.role,
            referral_code=self.referral_code,
            created_at=self.created_at,
        )
