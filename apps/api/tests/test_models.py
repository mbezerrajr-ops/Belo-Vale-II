import asyncio
import os
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Animal, Farm, ImageAsset, OfficialMeasurement


def _database_url() -> str:
    return os.getenv(
        "POSTGRES_URL",
        "postgresql+asyncpg://ingestion:ingestion@localhost:5432/ingestion",
    )


async def _create_farm_and_animal(session: AsyncSession) -> tuple[Farm, Animal]:
    farm = Farm(name="Fazenda Modelo")
    animal = Animal(farm=farm, identifier="BR-0001")
    session.add_all((farm, animal))
    await session.commit()
    return farm, animal


def test_same_image_hash_cannot_be_imported_twice() -> None:
    """Removing the farm/hash unique constraint must reject this test."""

    async def scenario() -> None:
        engine = create_async_engine(_database_url())
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                farm, _ = await _create_farm_and_animal(session)
                session.add_all(
                    (
                        ImageAsset(farm_id=farm.id, sha256="a" * 64),
                        ImageAsset(farm_id=farm.id, sha256="a" * 64),
                    )
                )
                with pytest.raises(IntegrityError):
                    await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_measurement_version_is_unique_when_active() -> None:
    """Removing the active-measurement index must reject this test."""

    async def scenario() -> None:
        engine = create_async_engine(_database_url())
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                _, animal = await _create_farm_and_animal(session)
                session.add_all(
                    (
                        OfficialMeasurement(
                            animal_id=animal.id,
                            measured_on=date(2026, 7, 22),
                            status="active",
                        ),
                        OfficialMeasurement(
                            animal_id=animal.id,
                            measured_on=date(2026, 7, 22),
                            status="active",
                        ),
                    )
                )
                with pytest.raises(IntegrityError):
                    await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(scenario())
