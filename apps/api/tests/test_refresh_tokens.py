"""Sessão longa via refresh token.

O token de acesso dura quinze minutos de propósito. Sem renovação, o
funcionário é desconectado no meio do trabalho no curral — e as saídas fáceis
(esticar o token, guardar em localStorage) trocam usabilidade por exposição.

O refresh resolve isso mantendo o acesso curto, desde que ele próprio seja
revogável e detecte roubo. É o que estes testes verificam.
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.security import hash_password
from app.db.models import RefreshToken, User
from app.services.refresh_tokens import (
    RefreshTokenError,
    hash_refresh_token,
    issue_refresh_token,
    revoke_all_for_user,
    revoke_refresh_token,
    rotate_refresh_token,
)

STRONG = "capim elefante molhado"


def _database_url() -> str:
    database_url = os.getenv("POSTGRES_URL")
    if not database_url:
        pytest.skip("POSTGRES_URL is required for PostgreSQL integration tests")
    return database_url


def _run(scenario):
    async def wrapper():
        engine = create_async_engine(_database_url(), poolclass=NullPool)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            await scenario(factory)
        finally:
            await engine.dispose()

    asyncio.run(wrapper())


async def _user(session: AsyncSession, email: str) -> User:
    user = User(
        email=email, password_hash=hash_password(STRONG), role="operator", is_active=True
    )
    session.add(user)
    await session.commit()
    return user


async def _stored(session: AsyncSession, raw: str) -> RefreshToken | None:
    return await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw))
    )


class TestIssue:
    def test_issues_an_opaque_token(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                user = await _user(session, "emissao@belovale")
                raw, record = await issue_refresh_token(session, user_id=user.id)

                assert len(raw) >= 32
                assert record.user_id == user.id
                assert record.expires_at > datetime.now(timezone.utc)
                assert record.used_at is None
                assert record.revoked_at is None

        _run(scenario)

    def test_never_stores_the_raw_token(self) -> None:
        """Quem ler o banco não pode assumir a sessão de ninguém."""

        async def scenario(factory) -> None:
            async with factory() as session:
                user = await _user(session, "hash@belovale")
                raw, record = await issue_refresh_token(session, user_id=user.id)

                assert record.token_hash != raw
                assert len(record.token_hash) == 64
                assert raw not in record.token_hash

        _run(scenario)

    def test_each_token_is_unique(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                user = await _user(session, "unico@belovale")
                first, _ = await issue_refresh_token(session, user_id=user.id)
                second, _ = await issue_refresh_token(session, user_id=user.id)

                assert first != second

        _run(scenario)


class TestRotation:
    def test_rotating_returns_a_new_token(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                user = await _user(session, "rotacao@belovale")
                first, _ = await issue_refresh_token(session, user_id=user.id)

                second, record = await rotate_refresh_token(session, raw_token=first)

                assert second != first
                assert record.user_id == user.id

        _run(scenario)

    def test_rotation_keeps_the_family(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                user = await _user(session, "familia@belovale")
                first, original = await issue_refresh_token(session, user_id=user.id)

                _, rotated = await rotate_refresh_token(session, raw_token=first)

                assert rotated.family_id == original.family_id

        _run(scenario)

    def test_the_old_token_stops_working(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                user = await _user(session, "antigo@belovale")
                first, _ = await issue_refresh_token(session, user_id=user.id)
                await rotate_refresh_token(session, raw_token=first)

                with pytest.raises(RefreshTokenError):
                    await rotate_refresh_token(session, raw_token=first)

        _run(scenario)

    def test_reuse_revokes_the_whole_family(self) -> None:
        """Um token já rotacionado reaparecendo indica roubo: derruba a sessão."""

        async def scenario(factory) -> None:
            async with factory() as session:
                user = await _user(session, "roubo@belovale")
                first, _ = await issue_refresh_token(session, user_id=user.id)
                second, _ = await rotate_refresh_token(session, raw_token=first)

                # O atacante usa o token antigo, que já havia sido rotacionado.
                with pytest.raises(RefreshTokenError):
                    await rotate_refresh_token(session, raw_token=first)

                # O token legítimo também deixa de valer: a sessão caiu inteira.
                with pytest.raises(RefreshTokenError):
                    await rotate_refresh_token(session, raw_token=second)

        _run(scenario)

    def test_unknown_token_is_rejected(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                with pytest.raises(RefreshTokenError):
                    await rotate_refresh_token(session, raw_token="inventado" * 5)

        _run(scenario)

    def test_expired_token_is_rejected(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                user = await _user(session, "expirado@belovale")
                raw, record = await issue_refresh_token(session, user_id=user.id)
                record.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
                await session.commit()

                with pytest.raises(RefreshTokenError):
                    await rotate_refresh_token(session, raw_token=raw)

        _run(scenario)

    def test_token_of_a_deactivated_user_is_rejected(self) -> None:
        """Desativar a conta precisa derrubar a sessão, não só o login."""

        async def scenario(factory) -> None:
            async with factory() as session:
                user = await _user(session, "desativado@belovale")
                raw, _ = await issue_refresh_token(session, user_id=user.id)
                user.is_active = False
                await session.commit()

                with pytest.raises(RefreshTokenError):
                    await rotate_refresh_token(session, raw_token=raw)

        _run(scenario)


class TestRevocation:
    def test_revoking_stops_the_token(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                user = await _user(session, "revoga@belovale")
                raw, _ = await issue_refresh_token(session, user_id=user.id)

                await revoke_refresh_token(session, raw_token=raw, reason="logout")

                with pytest.raises(RefreshTokenError):
                    await rotate_refresh_token(session, raw_token=raw)

        _run(scenario)

    def test_revoking_an_unknown_token_is_silent(self) -> None:
        """Logout com cookie velho não deve explodir na cara do usuário."""

        async def scenario(factory) -> None:
            async with factory() as session:
                await revoke_refresh_token(
                    session, raw_token="nao existe" * 4, reason="logout"
                )

        _run(scenario)

    def test_revoke_all_ends_every_session_of_the_user(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                user = await _user(session, "todas@belovale")
                celular, _ = await issue_refresh_token(session, user_id=user.id)
                computador, _ = await issue_refresh_token(session, user_id=user.id)

                await revoke_all_for_user(session, user_id=user.id, reason="account_disabled")

                for raw in (celular, computador):
                    with pytest.raises(RefreshTokenError):
                        await rotate_refresh_token(session, raw_token=raw)

        _run(scenario)

    def test_revoking_one_session_does_not_affect_another(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                user = await _user(session, "duas@belovale")
                celular, _ = await issue_refresh_token(session, user_id=user.id)
                computador, _ = await issue_refresh_token(session, user_id=user.id)

                await revoke_refresh_token(session, raw_token=celular, reason="logout")

                novo, _ = await rotate_refresh_token(session, raw_token=computador)
                assert novo

        _run(scenario)
