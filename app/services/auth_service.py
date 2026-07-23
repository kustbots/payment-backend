from app.core.timeutils import utcnow

from bson import ObjectId

from app.core.config import get_settings
from app.core.errors import AuthError, ConflictError, ValidationAppError
from app.core.security import create_access_token, create_refresh_token, decode_token, hash_password, verify_password
from app.db.mongo import users_col
from app.models.user import RegisterRequest, TokenResponse, UserInDB
from app.services.referral_service import generate_referral_code, resolve_referrer


async def register(payload: RegisterRequest) -> UserInDB:
    existing = await users_col().find_one({"email": payload.email.lower()})
    if existing:
        raise ConflictError("An account with this email already exists")

    referrer_id = await resolve_referrer(payload.referral_code)

    # Generate a unique referral code (unique index also enforces this, retry on rare collision).
    for _ in range(5):
        code = generate_referral_code()
        if not await users_col().find_one({"referral_code": code}):
            break
    else:
        raise ValidationAppError("Could not allocate a referral code, try again")

    settings = get_settings()
    role = "admin" if settings.ADMIN_BOOTSTRAP_EMAIL and payload.email.lower() == settings.ADMIN_BOOTSTRAP_EMAIL.lower() else "user"

    doc = {
        "email": payload.email.lower(),
        "hashed_password": hash_password(payload.password),
        "points": 0.0,
        "role": role,
        "referral_code": code,
        "referrer_id": referrer_id,
        "created_at": utcnow(),
        "is_active": True,
    }
    result = await users_col().insert_one(doc)
    doc["_id"] = result.inserted_id
    return UserInDB.from_mongo(doc)


async def authenticate(email: str, password: str) -> UserInDB:
    doc = await users_col().find_one({"email": email.lower()})
    if not doc or not verify_password(password, doc["hashed_password"]):
        raise AuthError("Invalid email or password")
    if not doc.get("is_active", True):
        raise AuthError("Account is disabled")
    return UserInDB.from_mongo(doc)


def issue_tokens(user: UserInDB) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user.id, user.role),
        refresh_token=create_refresh_token(user.id, user.role),
    )


async def refresh(refresh_token: str) -> TokenResponse:
    try:
        payload = decode_token(refresh_token)
    except ValueError as e:
        raise AuthError("Invalid or expired refresh token") from e

    if payload.get("type") != "refresh":
        raise AuthError("Invalid or expired refresh token")

    user_id = payload.get("sub")
    if not user_id or not ObjectId.is_valid(user_id):
        raise AuthError("Invalid or expired refresh token")

    doc = await users_col().find_one({"_id": ObjectId(user_id)})
    if not doc or not doc.get("is_active", True):
        raise AuthError("Invalid or expired refresh token")

    return issue_tokens(UserInDB.from_mongo(doc))
