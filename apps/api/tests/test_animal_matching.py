"""Matching de animais.

Contrato: o brinco é a **única** chave de correspondência automática. Nome não
identifica animal — a base tem nomes repetidos, e o mesmo nome em brincos
diferentes significa animais diferentes. Uma linha sem brinco legível não é
associada automaticamente a ninguém; vai para decisão humana.
"""

import asyncio
import os

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Animal, Farm
from app.services.animal_matching import (
    MATCH_BY_BRINCO,
    MATCH_NONE,
    find_animal_candidates,
    resolve_animal_match,
)


def _database_url() -> str:
    database_url = os.getenv("POSTGRES_URL")
    if not database_url:
        pytest.skip("POSTGRES_URL is required for PostgreSQL integration tests")
    return database_url


def _run(scenario):
    async def wrapper():
        engine = create_async_engine(_database_url())
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            await scenario(factory)
        finally:
            await engine.dispose()

    asyncio.run(wrapper())


class TestResolveAnimalMatch:
    def test_no_candidate_reports_no_match(self) -> None:
        result = resolve_animal_match([], brinco_lido="123", brinco_normalizado="123")
        assert result.animal is None
        assert result.is_ambiguous is False
        assert result.method == MATCH_NONE
        assert result.brinco_lido == "123"
        assert result.reason

    def test_single_candidate_is_matched_by_brinco(self) -> None:
        result = resolve_animal_match(
            ["a"],  # type: ignore[list-item]
            brinco_lido="B2- 008",
            brinco_normalizado="B2-008",
        )
        assert result.animal == "a"
        assert result.is_ambiguous is False
        assert result.candidate_count == 1
        assert result.method == MATCH_BY_BRINCO
        assert result.brinco_lido == "B2- 008"
        assert result.brinco_normalizado == "B2-008"

    def test_multiple_candidates_are_ambiguous_and_unmatched(self) -> None:
        result = resolve_animal_match(
            ["a", "b"],  # type: ignore[list-item]
            brinco_lido="777",
            brinco_normalizado="777",
        )
        assert result.animal is None
        assert result.is_ambiguous is True
        assert result.candidate_count == 2
        assert result.method == MATCH_NONE

    def test_result_records_why_it_did_not_match(self) -> None:
        unreadable = resolve_animal_match([], brinco_lido="B2-XXX", brinco_normalizado=None)
        assert "ilegível" in unreadable.reason.lower()

        absent = resolve_animal_match([], brinco_lido=None, brinco_normalizado=None)
        assert "sem brinco" in absent.reason.lower()


class TestFindAnimalCandidates:
    def test_matches_by_brinco(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = Farm(name="Match por brinco")
                session.add(farm)
                await session.commit()
                target = Animal(
                    farm_id=farm.id, identifier="v497", brinco="497", name="PONTA CURTA"
                )
                other = Animal(
                    farm_id=farm.id, identifier="v633", brinco="633", name="GIGANTE"
                )
                session.add_all([target, other])
                await session.commit()

                found = await find_animal_candidates(
                    session, farm_id=farm.id, brinco="497"
                )
                assert [a.id for a in found] == [target.id]

        _run(scenario)

    def test_normalizes_brinco_before_searching(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = Farm(name="Normaliza antes de buscar")
                session.add(farm)
                await session.commit()
                animal = Animal(farm_id=farm.id, identifier="v8", brinco="B2-008")
                session.add(animal)
                await session.commit()

                for raw in ("B2- 008", " b2-008 ", "B2-008"):
                    found = await find_animal_candidates(
                        session, farm_id=farm.id, brinco=raw
                    )
                    assert [a.id for a in found] == [animal.id], raw

        _run(scenario)

    def test_never_falls_back_to_name(self) -> None:
        """O ponto central deste contrato."""

        async def scenario(factory) -> None:
            async with factory() as session:
                farm = Farm(name="Sem fallback por nome")
                session.add(farm)
                await session.commit()
                session.add(
                    Animal(
                        farm_id=farm.id,
                        identifier="v100",
                        brinco="100",
                        name="MALHADA",
                    )
                )
                await session.commit()

                # Brinco desconhecido: não pode encontrar nada, ainda que o
                # nome exista na base.
                assert (
                    await find_animal_candidates(
                        session, farm_id=farm.id, brinco="999"
                    )
                    == []
                )
                # Sem brinco: idem.
                assert (
                    await find_animal_candidates(session, farm_id=farm.id, brinco=None)
                    == []
                )

        _run(scenario)

    def test_unreadable_brinco_matches_nothing(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = Farm(name="Brinco ilegivel")
                session.add(farm)
                await session.commit()
                session.add(
                    Animal(farm_id=farm.id, identifier="v1", brinco=None, name="SERRANA")
                )
                await session.commit()

                assert (
                    await find_animal_candidates(
                        session, farm_id=farm.id, brinco="B2-XXX"
                    )
                    == []
                )

        _run(scenario)

    def test_animals_without_brinco_are_never_returned(self) -> None:
        """142 animais da baseline não têm brinco e não podem ser casados."""

        async def scenario(factory) -> None:
            async with factory() as session:
                farm = Farm(name="Sem brinco nunca casa")
                session.add(farm)
                await session.commit()
                session.add_all(
                    [
                        Animal(farm_id=farm.id, identifier="v1", brinco=None, name="A"),
                        Animal(farm_id=farm.id, identifier="v2", brinco=None, name="B"),
                    ]
                )
                await session.commit()

                for brinco in (None, "", "   ", "B2-XXX"):
                    assert (
                        await find_animal_candidates(
                            session, farm_id=farm.id, brinco=brinco
                        )
                        == []
                    ), brinco

        _run(scenario)

    def test_matches_migrated_animal_whose_identifier_is_the_legacy_id(self) -> None:
        """Regressão: depois da migração, `identifier` é o legacy_id (`v389`).

        Buscar por `identifier` faria toda linha de OCR errar o brinco.
        """

        async def scenario(factory) -> None:
            async with factory() as session:
                farm = Farm(name="Animal migrado")
                session.add(farm)
                await session.commit()
                migrated = Animal(
                    farm_id=farm.id,
                    identifier="v389",
                    legacy_id="v389",
                    brinco="389",
                    numero_legado="389",
                    name="ÁGATA",
                )
                session.add(migrated)
                await session.commit()

                found = await find_animal_candidates(
                    session, farm_id=farm.id, brinco="389"
                )
                assert [a.id for a in found] == [migrated.id]

        _run(scenario)

    def test_same_name_different_brinco_are_different_animals(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = Farm(name="Nomes repetidos")
                session.add(farm)
                await session.commit()
                first = Animal(
                    farm_id=farm.id, identifier="v19", brinco="19", name="BOLINHA"
                )
                second = Animal(
                    farm_id=farm.id, identifier="v626", brinco="626", name="BOLINHA"
                )
                session.add_all([first, second])
                await session.commit()

                assert [
                    a.id
                    for a in await find_animal_candidates(
                        session, farm_id=farm.id, brinco="19"
                    )
                ] == [first.id]
                assert [
                    a.id
                    for a in await find_animal_candidates(
                        session, farm_id=farm.id, brinco="626"
                    )
                ] == [second.id]

        _run(scenario)

    def test_does_not_cross_farms(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                one = Farm(name="Fazenda A isolamento")
                other = Farm(name="Fazenda B isolamento")
                session.add_all([one, other])
                await session.commit()
                session.add(
                    Animal(farm_id=other.id, identifier="x1", brinco="555", name="X")
                )
                await session.commit()

                assert (
                    await find_animal_candidates(session, farm_id=one.id, brinco="555")
                    == []
                )

        _run(scenario)
