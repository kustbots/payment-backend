from fastapi import APIRouter, status

from app.models.user import LoginRequest, RefreshRequest, RegisterRequest, TokenResponse, UserOut
from app.services import auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest):
    user = await auth_service.register(payload)
    return user.to_out()


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest):
    user = await auth_service.authenticate(payload.email, payload.password)
    return auth_service.issue_tokens(user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest):
    return await auth_service.refresh(payload.refresh_token)
