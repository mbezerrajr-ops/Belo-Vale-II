import asyncio
import os
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Animal, ExtractedLine, ExtractionRun, Farm, ImageAsset, OfficialMeasurement
from app.services.approval import (
    ConcurrentReviewError,
    LineNotFoundError,
    MissingMeasurementDateError,
    ReplacementReasonRequiredError,
    UnmatchedAnimalError,
    decide_line,
)


def _database_url() -> str:
    database_url = os.getenv("POSTGRES_URL")
    if not database_url:
        pytest.skip("POSTGRES_URL is required for PostgreSQL integration tests")
    return database_url


async def _make_line(
    session: AsyncSession, *, animal_id: object = None, measured_on: str | None = "2026-07-22"
) -> ExtractedLine:
    farm = Farm(name="Fazenda Modelo")
    session.add(farm)
    await session.commit()

    image = ImageAsset(farm_id=farm.id, sha256=uuid4().hex.ljust(64, "0"))
    session.add(image)
    await session.flush()
    run = ExtractionRun(image_asset_id=image.id, status="extracted")
    session.add(run)
    await session.commit()

    line = ExtractedLine(
        extraction_run_id=run.id,
        line_number=1,
        raw_values={"total": "18"},
        normalized_values={"total": "18", "measured_on": measured_on},
        candidate_animal_id=animal_id,
    )
    session.add(line)
    await session.commit()
    return line


async def _make_animal(session: AsyncSession) -> Animal:
    farm = Farm(name="Fazenda Modelo")
    session.add(farm)
    await session.commit()
    animal = Animal(farm_id=farm.id, identifier="497", name="PONTA CURTA")
    session.add(animal)
    await session.commit()
    return animal


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


def test_approve_creates_an_active_measurement() -> None:
    async def scenario(session: AsyncSession) -> None:
        animal = await _make_animal(session)
        line = await _make_line(session, animal_id=animal.id)

        result = await decide_line(
            session,
            line_id=line.id,
            reviewer_email="reviewer@example.com",
            action="approve",
            corrected_values=None,
            reason="primeira aprovação",
            expected_version=1,
        )

        assert result.measurement_status == "active"
        measurement = await session.get(OfficialMeasurement, result.measurement_id)
        assert measurement.animal_id == animal.id
        assert measurement.measured_on == date(2026, 7, 22)
        assert measurement.status == "active"
        assert measurement.reviewed_by == "reviewer@example.com"

    _run(scenario)


def test_approve_supersedes_an_existing_measurement_with_a_reason() -> None:
    async def scenario(session: AsyncSession) -> None:
        animal = await _make_animal(session)
        first_line = await _make_line(session, animal_id=animal.id)
        first = await decide_line(
            session,
            line_id=first_line.id,
            reviewer_email="reviewer@example.com",
            action="approve",
            corrected_values=None,
            reason=None,
            expected_version=1,
        )

        second_line = await _make_line(session, animal_id=animal.id)
        second_line_id = second_line.id

        with pytest.raises(ReplacementReasonRequiredError):
            await decide_line(
                session,
                line_id=second_line_id,
                reviewer_email="reviewer@example.com",
                action="approve",
                corrected_values=None,
                reason=None,
                expected_version=1,
            )
        # A real request gets a fresh session per call; AsyncSession.close()
        # rolls back an in-flight transaction automatically on the way out.
        # Reusing one session across calls in this test needs that rollback
        # done explicitly, or the failed attempt's uncommitted version bump
        # would otherwise still be visible to the next call in this same
        # transaction. Rollback expires every ORM object in the session, so
        # only the plain UUID captured above is used afterward.
        await session.rollback()

        second = await decide_line(
            session,
            line_id=second_line_id,
            reviewer_email="reviewer@example.com",
            action="approve",
            corrected_values=None,
            reason="correção confirmada",
            expected_version=1,
        )

        assert second.measurement_status == "active"
        previous = await session.get(OfficialMeasurement, first.measurement_id)
        assert previous.status == "superseded"

    _run(scenario)


def test_reject_records_a_decision_without_creating_a_measurement() -> None:
    async def scenario(session: AsyncSession) -> None:
        animal = await _make_animal(session)
        line = await _make_line(session, animal_id=animal.id)

        result = await decide_line(
            session,
            line_id=line.id,
            reviewer_email="reviewer@example.com",
            action="reject",
            corrected_values=None,
            reason="foto ilegível",
            expected_version=1,
        )

        assert result.measurement_id is None
        assert result.measurement_status is None

    _run(scenario)


def test_stale_expected_version_is_rejected_and_prevents_double_approval() -> None:
    async def scenario(session: AsyncSession) -> None:
        animal = await _make_animal(session)
        line = await _make_line(session, animal_id=animal.id)

        await decide_line(
            session,
            line_id=line.id,
            reviewer_email="reviewer@example.com",
            action="approve",
            corrected_values=None,
            reason=None,
            expected_version=1,
        )

        with pytest.raises(ConcurrentReviewError):
            await decide_line(
                session,
                line_id=line.id,
                reviewer_email="reviewer@example.com",
                action="approve",
                corrected_values=None,
                reason="tentativa duplicada",
                expected_version=1,
            )

        measurements = await session.scalars(
            select(OfficialMeasurement).where(OfficialMeasurement.animal_id == animal.id)
        )
        assert len(list(measurements)) == 1

    _run(scenario)


def test_unmatched_animal_cannot_be_approved() -> None:
    async def scenario(session: AsyncSession) -> None:
        line = await _make_line(session, animal_id=None)

        with pytest.raises(UnmatchedAnimalError):
            await decide_line(
                session,
                line_id=line.id,
                reviewer_email="reviewer@example.com",
                action="approve",
                corrected_values=None,
                reason=None,
                expected_version=1,
            )

    _run(scenario)


def test_missing_measured_on_cannot_be_approved() -> None:
    async def scenario(session: AsyncSession) -> None:
        animal = await _make_animal(session)
        line = await _make_line(session, animal_id=animal.id, measured_on=None)

        with pytest.raises(MissingMeasurementDateError):
            await decide_line(
                session,
                line_id=line.id,
                reviewer_email="reviewer@example.com",
                action="approve",
                corrected_values=None,
                reason=None,
                expected_version=1,
            )

    _run(scenario)


def test_unknown_line_raises_not_found() -> None:
    async def scenario(session: AsyncSession) -> None:
        with pytest.raises(LineNotFoundError):
            await decide_line(
                session,
                line_id=uuid4(),
                reviewer_email="reviewer@example.com",
                action="reject",
                corrected_values=None,
                reason=None,
                expected_version=1,
            )

    _run(scenario)


def test_corrected_values_override_normalized_values_in_the_stored_measurement() -> None:
    async def scenario(session: AsyncSession) -> None:
        animal = await _make_animal(session)
        line = await _make_line(session, animal_id=animal.id)

        result = await decide_line(
            session,
            line_id=line.id,
            reviewer_email="reviewer@example.com",
            action="approve",
            corrected_values={"total": "19"},
            reason=None,
            expected_version=1,
        )

        measurement = await session.get(OfficialMeasurement, result.measurement_id)
        assert measurement.values["total"] == "19"

    _run(scenario)


def test_two_reviewers_racing_on_the_same_animal_and_date_cannot_both_win_silently() -> None:
    """Operator A opens the review and sees existing_measurement = None.
    Before A submits, operator B approves a different extracted line for the
    same animal + date. A's stale view must not let their approval silently
    win or silently lose — the backend must force an explicit replacement
    decision, never a silent overwrite."""

    async def scenario(session: AsyncSession) -> None:
        animal = await _make_animal(session)
        animal_id = animal.id
        line_seen_by_a = await _make_line(session, animal_id=animal_id)
        line_seen_by_a_id = line_seen_by_a.id
        line_approved_by_b = await _make_line(session, animal_id=animal_id)

        # A's view of the world at review time: no active measurement yet.
        existing_before_b = await session.scalar(
            select(OfficialMeasurement).where(OfficialMeasurement.animal_id == animal_id)
        )
        assert existing_before_b is None

        # B approves first.
        b_result = await decide_line(
            session,
            line_id=line_approved_by_b.id,
            reviewer_email="operator-b@example.com",
            action="approve",
            corrected_values=None,
            reason=None,
            expected_version=1,
        )
        assert b_result.measurement_status == "active"

        # A now tries to approve, still holding the version they originally
        # saw. The backend must reject a silent overwrite...
        with pytest.raises(ReplacementReasonRequiredError):
            await decide_line(
                session,
                line_id=line_seen_by_a_id,
                reviewer_email="operator-a@example.com",
                action="approve",
                corrected_values=None,
                reason=None,
                expected_version=1,
            )
        # A real request gets its own session; reusing this one across calls
        # needs the rollback AsyncSession.close() would otherwise do, so the
        # rejected attempt's uncommitted version bump doesn't leak forward.
        await session.rollback()

        # ...but an explicit, reasoned replacement is allowed and auditable.
        a_result = await decide_line(
            session,
            line_id=line_seen_by_a_id,
            reviewer_email="operator-a@example.com",
            action="approve",
            corrected_values=None,
            reason="B aprovou primeiro; confirmando valor de A após conferência",
            expected_version=1,
        )
        assert a_result.measurement_status == "active"

        b_measurement = await session.get(OfficialMeasurement, b_result.measurement_id)
        assert b_measurement.status == "superseded"

        active_count = await session.scalars(
            select(OfficialMeasurement).where(
                OfficialMeasurement.animal_id == animal_id,
                OfficialMeasurement.status == "active",
            )
        )
        assert len(list(active_count)) == 1

    _run(scenario)
