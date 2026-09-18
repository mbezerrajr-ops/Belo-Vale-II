import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.login_throttle import LoginThrottle, get_login_throttle
from app.core.security import create_access_token, get_current_user, hash_password, verify_password
from app.db.models import User
from app.db.session import get_db_session
from app.schemas.auth import CurrentUserResponse, LoginRequest, TokenResponse


router = APIRouter(prefix="/api/auth", tags=["auth"])
_DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(32))


@router.post("/login", response_model=TokenResponse)
async def login(
    credentials: LoginRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    throttle: Annotated[LoginThrottle, Depends(get_login_throttle)],
) -> TokenResponse:
    email = credentials.email.strip().lower()
    # `request.client.host` é o par TCP imediato. Atrás de proxy reverso, o
    # uvicorn precisa rodar com --proxy-headers para que este valor seja o do
    # cliente real; confiar em X-Forwarded-For sem isso permitiria a qualquer
    # um forjar a origem e escapar do limite.
    origin = request.client.host if request.client else "desconhecida"

    retry_after = throttle.check(email, origin)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Muitas tentativas de login. "
                f"Tente novamente em {max(1, retry_after // 60)} minuto(s)."
            ),
            headers={"Retry-After": str(retry_after)},
        )

    user = await session.scalar(select(User).where(func.lower(User.email) == email))
    password_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    password_is_valid = verify_password(credentials.password, password_hash)
    if user is None or not user.is_active or not password_is_valid:
        # A mesma resposta para conta inexistente, inativa e senha errada:
        # distinguir revelaria quais e-mails existem no sistema.
        throttle.record_failure(email, origin)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    throttle.record_success(email, origin)
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
