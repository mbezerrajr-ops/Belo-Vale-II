import asyncio
import os

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Animal, Farm
from app.services.animal_matching import find_animal_candidates, resolve_animal_match


def _database_url() -> str:
    database_url = os.getenv("POSTGRES_URL")
    if not database_url:
        pytest.skip("POSTGRES_URL is required for PostgreSQL integration tests")
    return database_url


def test_resolve_animal_match_reports_unknown_ambiguous_and_matched() -> None:
    assert resolve_animal_match([]).animal is None
    assert resolve_animal_match([]).is_ambiguous is False

    ambiguous = resolve_animal_match(["a", "b"])  # type: ignore[list-item]
    assert ambiguous.animal is None
    assert ambiguous.is_ambiguous is True
    assert ambiguous.candidate_count == 2

    matched = resolve_animal_match(["a"])  # type: ignore[list-item]
    assert matched.animal == "a"
    assert matched.is_ambiguous is False
    assert matched.candidate_count == 1


def test_find_animal_candidates_matches_by_tag_before_name() -> None:
    async def scenario() -> None:
        engine = create_async_engine(_database_url())
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                farm = Farm(name="Fazenda Modelo")
                session.add(farm)
                await session.commit()

                target = Animal(farm_id=farm.id, identifier="497", name="PONTA CURTA")
                decoy = Animal(farm_id=farm.id, identifier="633", name="GIGANTE")
                session.add_all([target, decoy])
                await session.commit()

                by_tag = await find_animal_candidates(
                    session, farm_id=farm.id, animal_number="497", animal_name="qualquer coisa"
                )
                assert [animal.id for animal in by_tag] == [target.id]

                by_name = await find_animal_candidates(
                    session, farm_id=farm.id, animal_number=None, animal_name="ponta curta"
                )
                assert [animal.id for animal in by_name] == [target.id]

                none_found = await find_animal_candidates(
                    session, farm_id=farm.id, animal_number="999", animal_name=None
                )
                assert none_found == []
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_find_animal_candidates_reports_ambiguity_by_name() -> None:
    async def scenario() -> None:
        engine = create_async_engine(_database_url())
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                farm = Farm(name="Fazenda Modelo")
                session.add(farm)
                await session.commit()

                session.add_all(
                    [
                        Animal(farm_id=farm.id, identifier="1", name="MALHADA"),
                        Animal(farm_id=farm.id, identifier="2", name="Malhada"),
                    ]
                )
                await session.commit()

                candidates = await find_animal_candidates(
                    session, farm_id=farm.id, animal_number=None, animal_name="malhada"
                )
                assert len(candidates) == 2
                assert resolve_animal_match(candidates).is_ambiguous is True
        finally:
            await engine.dispose()

    asyncio.run(scenario())
