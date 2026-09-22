import asyncio
import os
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import (
    Animal,
    ExtractedLine,
    ExtractionRun,
    Farm,
    MediaAsset,
    Import,
    OfficialMeasurement,
    ReviewDecision,
)
from app.services.measurements import list_active_measurements


def _database_url() -> str:
    database_url = os.getenv("POSTGRES_URL")
    if not database_url:
        pytest.skip("POSTGRES_URL is required for PostgreSQL integration tests")
    return database_url


def _run(coro_factory) -> None:
    async def scenario() -> None:
        engine = create_async_engine(_database_url())
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                await coro_factory(session)
        finally:
            await engine.dispose()

    asyncio.run(scenario())


async def _approved_measurement(
    session: AsyncSession,
    *,
    farm: Farm,
    animal: Animal,
    measured_on: date,
    total: str,
    status: str = "active",
) -> OfficialMeasurement:
    image = MediaAsset(farm_id=farm.id, sha256=os.urandom(32).hex())
    session.add(image)
    await session.flush()
    run = ExtractionRun(media_asset_id=image.id, status="extracted")
    session.add(run)
    await session.flush()
    line = ExtractedLine(extraction_run_id=run.id, line_number=1, raw_values={})
    session.add(line)
    await session.flush()
    review = ReviewDecision(extracted_line_id=line.id, actor="reviewer@example.com", decision="approved")
    session.add(review)
    await session.flush()

    measurement = OfficialMeasurement(
        animal_id=animal.id,
        review_decision_id=review.id,
        measured_on=measured_on,
        values={"total": total},
        status=status,
        reviewed_by="reviewer@example.com",
    )
    session.add(measurement)
    await session.commit()
    return measurement


def test_history_hides_superseded_measurements() -> None:
    async def scenario(session: AsyncSession) -> None:
        farm = Farm(name="Fazenda Modelo")
        session.add(farm)
        await session.commit()
        animal = Animal(farm_id=farm.id, identifier="497", name="PONTA CURTA")
        session.add(animal)
        await session.commit()

        superseded = await _approved_measurement(
            session, farm=farm, animal=animal, measured_on=date(2026, 7, 21), total="17", status="superseded"
        )
        active = await _approved_measurement(
            session, farm=farm, animal=animal, measured_on=date(2026, 7, 22), total="18"
        )

        records = await list_active_measurements(
            session, farm_id=farm.id, date_from=None, date_to=None
        )

        assert [record.id for record in records] == [active.id]
        assert superseded.id not in [record.id for record in records]

    _run(scenario)


def test_history_filters_by_farm_and_date_range() -> None:
    async def scenario(session: AsyncSession) -> None:
        farm_a = Farm(name="Fazenda A")
        farm_b = Farm(name="Fazenda B")
        session.add_all([farm_a, farm_b])
        await session.commit()

        animal_a = Animal(farm_id=farm_a.id, identifier="1", name="A1")
        animal_b = Animal(farm_id=farm_b.id, identifier="1", name="B1")
        session.add_all([animal_a, animal_b])
        await session.commit()

        in_range = await _approved_measurement(
            session, farm=farm_a, animal=animal_a, measured_on=date(2026, 7, 15), total="20"
        )
        await _approved_measurement(
            session, farm=farm_a, animal=animal_a, measured_on=date(2026, 6, 1), total="19"
        )
        await _approved_measurement(
            session, farm=farm_b, animal=animal_b, measured_on=date(2026, 7, 15), total="21"
        )

        records = await list_active_measurements(
            session,
            farm_id=farm_a.id,
            date_from=date(2026, 7, 1),
            date_to=date(2026, 7, 31),
        )

        assert [record.id for record in records] == [in_range.id]

    _run(scenario)
