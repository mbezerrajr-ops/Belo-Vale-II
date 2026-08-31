import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import create_access_token, get_current_user, hash_password, verify_password
from app.db.models import User
from app.db.session import get_db_session
from app.schemas.auth import CurrentUserResponse, LoginRequest, TokenResponse


router = APIRouter(prefix="/api/auth", tags=["auth"])
_DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(32))


@router.post("/login", response_model=TokenResponse)
async def login(
    credentials: LoginRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse:
    email = credentials.email.strip().lower()
    user = await session.scalar(select(User).where(func.lower(User.email) == email))
    password_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    password_is_valid = verify_password(credentials.password, password_hash)
    if user is None or not user.is_active or not password_is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        token = create_access_token(
            user.id, settings.auth_secret, settings.auth_token_ttl_seconds
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured",
        ) from exc
    return TokenResponse(
        access_token=token,
        expires_in=settings.auth_token_ttl_seconds,
    )


@router.get("/me", response_model=CurrentUserResponse)
async def current_user(
    user: Annotated[User, Depends(get_current_user)],
) -> CurrentUserResponse:
    return CurrentUserResponse(
        id=str(user.id), email=user.email, role=user.role
    )
