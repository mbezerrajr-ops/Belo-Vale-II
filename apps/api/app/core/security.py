from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.models import User
from app.db.session import get_db_session


Role = Literal["operator", "reviewer", "admin"]
_ROLE_LEVEL: dict[str, int] = {"operator": 10, "reviewer": 20, "admin": 30}
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_LENGTH = 32
_bearer = HTTPBearer(auto_error=False)


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("password cannot be empty")
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_LENGTH,
    )
    return "$".join(
        (
            "scrypt",
            str(_SCRYPT_N),
            str(_SCRYPT_R),
            str(_SCRYPT_P),
            _base64url_encode(salt),
            _base64url_encode(derived),
        )
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_base64url_decode(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(_base64url_decode(expected)),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(derived, _base64url_decode(expected))


def _secret_bytes(secret: SecretStr | str | None) -> bytes:
    if secret is None:
        raise RuntimeError("AUTH_SECRET is required to issue or validate credentials")
    value = secret.get_secret_value() if isinstance(secret, SecretStr) else secret
    if len(value.encode("utf-8")) < 32:
        raise RuntimeError("AUTH_SECRET must contain at least 32 bytes")
    return value.encode("utf-8")


def create_access_token(
    user_id: UUID,
    secret: SecretStr | str | None,
    ttl_seconds: int,
    *,
    now: datetime | None = None,
) -> str:
    issued_at = int((now or datetime.now(timezone.utc)).timestamp())
    header = _base64url_encode(
        json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode()
    )
    payload = _base64url_encode(
        json.dumps(
            {"sub": str(user_id), "iat": issued_at, "exp": issued_at + ttl_seconds},
            separators=(",", ":"),
        ).encode()
    )
    signing_input = f"{header}.{payload}".encode("ascii")
    signature = _base64url_encode(
        hmac.new(_secret_bytes(secret), signing_input, hashlib.sha256).digest()
    )
    return f"{header}.{payload}.{signature}"


def decode_access_token(
    token: str,
    secret: SecretStr | str | None,
    *,
    now: datetime | None = None,
) -> UUID:
    try:
        header_encoded, payload_encoded, signature_encoded = token.split(".", 2)
        signing_input = f"{header_encoded}.{payload_encoded}".encode("ascii")
        expected_signature = hmac.new(
            _secret_bytes(secret), signing_input, hashlib.sha256
        ).digest()
        if not hmac.compare_digest(
            expected_signature, _base64url_decode(signature_encoded)
        ):
            raise ValueError("invalid signature")
        header = json.loads(_base64url_decode(header_encoded))
        payload = json.loads(_base64url_decode(payload_encoded))
        if header != {"alg": "HS256", "typ": "JWT"}:
            raise ValueError("unsupported token header")
        current_timestamp = int((now or datetime.now(timezone.utc)).timestamp())
        if not isinstance(payload.get("exp"), int) or payload["exp"] <= current_timestamp:
            raise ValueError("expired token")
        if not isinstance(payload.get("iat"), int) or payload["iat"] > current_timestamp:
            raise ValueError("invalid issued-at time")
        return UUID(payload["sub"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid or expired access token") from exc


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_authenticated_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    """Conta autenticada, mesmo que ainda precise trocar a senha provisória.

    Só as rotas de "quem sou eu" e de troca de senha usam esta dependência;
    todo o resto passa por :func:`get_current_user`.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()
    try:
        user_id = decode_access_token(credentials.credentials, settings.auth_secret)
    except (RuntimeError, ValueError) as exc:
        raise _unauthorized() from exc
    user = await session.scalar(
        select(User).where(User.id == user_id, User.is_active.is_(True))
    )
    if user is None:
        raise _unauthorized()
    return user


async def get_current_user(
    user: Annotated[User, Depends(get_authenticated_user)],
) -> User:
    """Conta autenticada e liberada para usar o sistema.

    Depois de uma redefinição feita pelo administrador, a senha provisória já
    passou por outras mãos; até o dono da conta escolher uma nova, ela só
    serve para isso.
    """
    if user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Troque a senha provisória antes de continuar.",
        )
    return user


def has_minimum_role(user: User, minimum_role: Role) -> bool:
    return _ROLE_LEVEL.get(user.role, -1) >= _ROLE_LEVEL[minimum_role]


def require_minimum_role(minimum_role: Role) -> Callable[..., User]:
    minimum_level = _ROLE_LEVEL[minimum_role]

    async def dependency(
        user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        if _ROLE_LEVEL.get(user.role, -1) < minimum_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role",
            )
        return user

    return dependency
