import asyncio
import os
from datetime import date
from uuid import UUID

import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import (
    Animal,
    ExtractedLine,
    ExtractionRun,
    Farm,
    ImageAsset,
    Import,
    OfficialMeasurement,
    ReviewDecision,
)


def _database_url() -> str:
    database_url = os.getenv("POSTGRES_URL")
    if not database_url:
        pytest.skip("POSTGRES_URL is required for PostgreSQL integration tests")
    return database_url


async def _create_farm_and_animal(session: AsyncSession) -> tuple[Farm, Animal]:
    farm = Farm(name="Fazenda Modelo")
    animal = Animal(farm=farm, identifier="BR-0001")
    session.add_all((farm, animal))
    await session.commit()
    return farm, animal


async def _create_review_decision(
    session: AsyncSession, farm_id: UUID, decision: str = "approved"
) -> ReviewDecision:
    ingestion = Import(farm_id=farm_id)
    session.add(ingestion)
    await session.flush()

    image = ImageAsset(farm_id=farm_id, import_id=ingestion.id, sha256="b" * 64)
    session.add(image)
    await session.flush()

    run = ExtractionRun(image_asset_id=image.id)
    session.add(run)
    await session.flush()

    line = ExtractedLine(extraction_run_id=run.id, line_number=1, raw_values={})
    session.add(line)
    await session.flush()

    review = ReviewDecision(extracted_line_id=line.id, actor="reviewer@example.com", decision=decision)
    session.add(review)
    await session.commit()
    return review


def _measurement(
    animal_id: UUID, review: ReviewDecision, status: str = "active"
) -> OfficialMeasurement:
    return OfficialMeasurement(
        animal_id=animal_id,
        review_decision_id=review.id,
        reviewed_by=review.actor,
        measured_on=date(2026, 7, 22),
        status=status,
    )


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
                farm, animal = await _create_farm_and_animal(session)
                review = await _create_review_decision(session, farm.id)
                session.add_all(
                    (
                        _measurement(animal.id, review),
                        _measurement(animal.id, review),
                    )
                )
                with pytest.raises(IntegrityError):
                    await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_superseded_measurement_can_coexist_with_one_active_version() -> None:
    """Replacing the partial index with an unconditional one must reject this test."""

    async def scenario() -> None:
        engine = create_async_engine(_database_url())
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                farm, animal = await _create_farm_and_animal(session)
                review = await _create_review_decision(session, farm.id)
                session.add_all((_measurement(animal.id, review), _measurement(animal.id, review, "superseded")))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_measurement_rejects_a_status_outside_the_domain() -> None:
    """Removing the measurement status check constraint must reject this test."""

    async def scenario() -> None:
        engine = create_async_engine(_database_url())
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                _, animal = await _create_farm_and_animal(session)
                session.add(
                    OfficialMeasurement(
                        animal_id=animal.id,
                        measured_on=date(2026, 7, 22),
                        status="draft",
                    )
                )
                with pytest.raises(IntegrityError):
                    await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_active_measurement_requires_approved_review_provenance_and_actor() -> None:
    """Removing the active-review constraint or approval trigger must reject this test."""

    async def scenario() -> None:
        engine = create_async_engine(_database_url())
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                farm, animal = await _create_farm_and_animal(session)
                farm_id = farm.id
                animal_id = animal.id
                session.add(
                    OfficialMeasurement(
                        animal_id=animal.id,
                        measured_on=date(2026, 7, 22),
                        status="active",
                    )
                )
                with pytest.raises(DBAPIError):
                    await session.commit()
                await session.rollback()

                rejected_review = await _create_review_decision(session, farm_id, decision="rejected")
                session.add(_measurement(animal_id, rejected_review))
                with pytest.raises(DBAPIError):
                    await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(scenario())
