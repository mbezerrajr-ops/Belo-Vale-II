"""Sessão longa via refresh token.

O token de acesso dura quinze minutos de propósito: se vazar, o estrago tem
prazo curto. Mas quinze minutos sem renovação desconectam o funcionário no
meio do trabalho, e as saídas fáceis — esticar o token, guardá-lo em
``localStorage`` — trocam usabilidade por exposição.

O refresh resolve isso mantendo o acesso curto. Para que ele próprio não vire
o elo fraco, três decisões:

- **Só o hash é persistido.** Quem obtiver leitura do banco não assume a
  sessão de ninguém.
- **Rotação a cada uso.** Um token vale uma vez; usá-lo devolve outro.
- **Reuso derruba a família inteira.** Se um token já rotacionado reaparece,
  ou o legítimo foi roubado ou o ladrão chegou antes — em ambos os casos a
  sessão inteira cai, porque não dá para saber qual dos dois é o dono.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RefreshToken, User

#: Validade da sessão. Longa o bastante para não incomodar quem usa o sistema
#: todo dia, curta o bastante para que um cookie esquecido não valha para
#: sempre.
DEFAULT_TTL_SECONDS = 30 * 24 * 60 * 60

#: Bytes de entropia do token. 32 bytes tornam a adivinhação inviável.
_TOKEN_BYTES = 32


class RefreshTokenError(Exception):
    """Sessão inválida. A mensagem é deliberadamente genérica: distinguir
    "não existe" de "expirou" de "foi revogado" ajudaria um atacante a mapear
    o estado das sessões."""


def hash_refresh_token(raw_token: str) -> str:
    """SHA-256 simples, sem salt e sem custo alto de propósito.

    Diferente de senha, este valor já tem 256 bits de entropia aleatória: não
    há dicionário a testar, então derivação lenta só encareceria o caminho
    legítimo, que roda a cada renovação.
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def issue_refresh_token(
    session: AsyncSession,
    *,
    user_id: UUID,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    family_id: UUID | None = None,
) -> tuple[str, RefreshToken]:
    """Cria uma sessão nova. Devolve ``(token em claro, registro)``.

    O valor em claro existe apenas nesta resposta: é gravado no cookie e nunca
    mais fica disponível.
    """
    raw_token = secrets.token_urlsafe(_TOKEN_BYTES)
    record = RefreshToken(
        user_id=user_id,
        token_hash=hash_refresh_token(raw_token),
        family_id=family_id or uuid4(),
        expires_at=_now() + timedelta(seconds=ttl_seconds),
    )
    session.add(record)
    await session.commit()
    return raw_token, record


async def _revoke_family(
    session: AsyncSession, *, family_id: UUID, reason: str
) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now(), revoked_reason=reason)
    )
    await session.commit()


async def rotate_refresh_token(
    session: AsyncSession, *, raw_token: str, ttl_seconds: int = DEFAULT_TTL_SECONDS
) -> tuple[str, RefreshToken]:
    """Troca um refresh válido por outro, encerrando o anterior."""
    record = await session.scalar(
        select(RefreshToken).where(
            RefreshToken.token_hash == hash_refresh_token(raw_token)
        )
    )
    if record is None:
        raise RefreshTokenError("Sessão inválida.")

    if record.used_at is not None:
        # Este token já foi trocado. Ou o legítimo foi roubado e o ladrão
        # chegou depois, ou o ladrão chegou antes e o legítimo veio agora.
        # Não há como distinguir, então a sessão inteira cai.
        await _revoke_family(
            session, family_id=record.family_id, reason="reuse_detected"
        )
        raise RefreshTokenError("Sessão inválida.")

    if record.revoked_at is not None:
        raise RefreshTokenError("Sessão inválida.")

    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= _now():
        raise RefreshTokenError("Sessão inválida.")

    user = await session.scalar(
        select(User).where(User.id == record.user_id, User.is_active.is_(True))
    )
    if user is None:
        # Desativar a conta precisa derrubar a sessão, não só impedir o login.
        await _revoke_family(
            session, family_id=record.family_id, reason="user_inactive"
        )
        raise RefreshTokenError("Sessão inválida.")

    record.used_at = _now()
    raw_next = secrets.token_urlsafe(_TOKEN_BYTES)
    successor = RefreshToken(
        user_id=record.user_id,
        token_hash=hash_refresh_token(raw_next),
        family_id=record.family_id,
        expires_at=_now() + timedelta(seconds=ttl_seconds),
    )
    session.add(successor)
    await session.commit()
    return raw_next, successor


async def revoke_refresh_token(
    session: AsyncSession, *, raw_token: str, reason: str
) -> None:
    """Encerra uma sessão. Silencioso quando o token não existe, para que um
    logout com cookie velho não vire erro na cara do usuário."""
    record = await session.scalar(
        select(RefreshToken).where(
            RefreshToken.token_hash == hash_refresh_token(raw_token)
        )
    )
    if record is None:
        return
    await _revoke_family(session, family_id=record.family_id, reason=reason)


async def revoke_all_for_user(
    session: AsyncSession, *, user_id: UUID, reason: str
) -> None:
    """Derruba todas as sessões da pessoa, em todos os dispositivos."""
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now(), revoked_reason=reason)
    )
    await session.commit()


async def purge_expired(session: AsyncSession, *, older_than_days: int = 7) -> int:
    """Remove registros vencidos há tempo suficiente para não servirem mais
    nem à investigação de um incidente."""
    cutoff = _now() - timedelta(days=older_than_days)
    result = await session.execute(
        RefreshToken.__table__.delete().where(RefreshToken.expires_at < cutoff)
    )
    await session.commit()
    return result.rowcount or 0
