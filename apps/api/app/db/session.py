from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings


def build_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    if not settings.postgres_url:
        raise RuntimeError("postgres_url is required to create database sessions")

    engine = create_async_engine(settings.postgres_url, pool_pre_ping=True)
    return async_sessionmaker(engine, expire_on_commit=False)


async def session_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return build_session_factory(get_settings())


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session
