import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.login_throttle import LoginThrottle, get_login_throttle
from app.services.refresh_tokens import (
    RefreshTokenError,
    issue_refresh_token,
    revoke_refresh_token,
    rotate_refresh_token,
)
from app.core.security import create_access_token, get_current_user, hash_password, verify_password
from app.db.models import User
from app.db.session import get_db_session
from app.schemas.auth import CurrentUserResponse, LoginRequest, TokenResponse


router = APIRouter(prefix="/api/auth", tags=["auth"])

#: Nome do cookie de sessão.
REFRESH_COOKIE = "bv_refresh"
#: Restrito ao próprio caminho de autenticação: o cookie não acompanha as
#: demais chamadas da API, então nem é exposto onde não faz falta.
_COOKIE_PATH = "/api/auth"


def _set_refresh_cookie(
    response: Response, raw_token: str, settings: Settings
) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        raw_token,
        max_age=settings.auth_refresh_ttl_seconds,
        path=_COOKIE_PATH,
        # HttpOnly: JavaScript não lê, então um XSS não leva a sessão embora.
        httponly=True,
        # Secure: sem TLS o cookie viajaria em texto puro.
        secure=settings.auth_cookie_secure,
        # Strict: frontend e API compartilham origem (o nginx serve os dois),
        # então o cookie nunca precisa acompanhar navegação de outro site —
        # o que já barra CSRF sem token adicional.
        samesite="strict",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=_COOKIE_PATH)
_DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(32))


@router.post("/login", response_model=TokenResponse)
async def login(
    credentials: LoginRequest,
    request: Request,
    response: Response,
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
    raw_refresh, _ = await issue_refresh_token(
        session, user_id=user.id, ttl_seconds=settings.auth_refresh_ttl_seconds
    )
    _set_refresh_cookie(response, raw_refresh, settings)
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


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse:
    """Troca a sessão por um token de acesso novo.

    O acesso continua curto; é esta chamada que permite ao usuário trabalhar
    sem refazer login. O refresh é rotacionado a cada uso.
    """
    raw_token = request.cookies.get(REFRESH_COOKIE)
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sessão expirada. Entre novamente.",
        )
    try:
        raw_next, record = await rotate_refresh_token(
            session,
            raw_token=raw_token,
            ttl_seconds=settings.auth_refresh_ttl_seconds,
        )
    except RefreshTokenError as error:
        # Cookie inútil só atrapalha: some com ele para o usuário poder
        # simplesmente entrar de novo.
        _clear_refresh_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sessão expirada. Entre novamente.",
        ) from error

    try:
        access_token = create_access_token(
            record.user_id, settings.auth_secret, settings.auth_token_ttl_seconds
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured",
        ) from exc

    _set_refresh_cookie(response, raw_next, settings)
    return TokenResponse(
        access_token=access_token, expires_in=settings.auth_token_ttl_seconds
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Response:
    """Encerra a sessão. Não exige token de acesso válido: quem quer sair
    deve conseguir sair mesmo com o acesso já vencido."""
    raw_token = request.cookies.get(REFRESH_COOKIE)
    if raw_token:
        await revoke_refresh_token(session, raw_token=raw_token, reason="logout")
    _clear_refresh_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
