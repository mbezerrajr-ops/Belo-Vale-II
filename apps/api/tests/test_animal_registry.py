"""Cadastro mestre de animais.

Toda mutação aqui é deliberada e humana, ao contrário da ingestão automática.
Por isso todas são auditadas, e as regras de identidade valem igual: brinco é
único quando presente, nome nunca identifica, lote é histórico.
"""

import asyncio
import os
from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Animal, AnimalLotAssignment, AuditEvent, Farm
from app.services.animal_registry import (
    AnimalRegistryError,
    assign_lot,
    create_animal,
    link_brinco,
    update_animal,
)

ACTOR = "revisor@belovale"


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


async def _farm(session: AsyncSession, name: str) -> Farm:
    farm = Farm(name=name)
    session.add(farm)
    await session.commit()
    return farm


async def _audit_actions(session: AsyncSession, entity_id) -> list[str]:
    return list(
        await session.scalars(
            select(AuditEvent.action)
            .where(AuditEvent.entity_id == entity_id)
            .order_by(AuditEvent.created_at)
        )
    )


class TestCreateAnimal:
    def test_creates_with_brinco_normalized(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _farm(session, "Criar com brinco")
                animal = await create_animal(
                    session,
                    farm_id=farm.id,
                    actor=ACTOR,
                    brinco="b2- 008",
                    name="Cabelo de Fogo",
                )
                assert animal.brinco == "B2-008"
                assert animal.brinco_origem == "b2- 008"
                assert animal.identifier
                assert await _audit_actions(session, animal.id) == ["animal_created"]

        _run(scenario)

    def test_creates_without_brinco(self) -> None:
        """Um animal pode entrar no cadastro sem brinco."""

        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _farm(session, "Criar sem brinco")
                animal = await create_animal(
                    session, farm_id=farm.id, actor=ACTOR, brinco=None, name="SEM BRINCO"
                )
                assert animal.brinco is None
                assert animal.id is not None

        _run(scenario)

    def test_rejects_duplicate_brinco(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _farm(session, "Brinco duplicado cadastro")
                await create_animal(
                    session, farm_id=farm.id, actor=ACTOR, brinco="500", name="A"
                )
                with pytest.raises(AnimalRegistryError) as excinfo:
                    await create_animal(
                        session, farm_id=farm.id, actor=ACTOR, brinco="500", name="B"
                    )
                assert "brinco" in str(excinfo.value).lower()

        _run(scenario)

    def test_allows_duplicate_names(self) -> None:
        """Nome não identifica: BOLINHA pode existir duas vezes."""

        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _farm(session, "Nomes repetidos cadastro")
                first = await create_animal(
                    session, farm_id=farm.id, actor=ACTOR, brinco="19", name="BOLINHA"
                )
                second = await create_animal(
                    session, farm_id=farm.id, actor=ACTOR, brinco="626", name="BOLINHA"
                )
                assert first.id != second.id

        _run(scenario)

    def test_rejects_unreadable_brinco(self) -> None:
        """Numa ação humana deliberada, um placeholder não passa silenciosamente."""

        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _farm(session, "Brinco ilegivel cadastro")
                with pytest.raises(AnimalRegistryError) as excinfo:
                    await create_animal(
                        session, farm_id=farm.id, actor=ACTOR, brinco="B2-XXX", name="X"
                    )
                assert "ilegível" in str(excinfo.value).lower()

        _run(scenario)

    def test_creates_initial_lot_assignment(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _farm(session, "Lote inicial")
                animal = await create_animal(
                    session,
                    farm_id=farm.id,
                    actor=ACTOR,
                    brinco="700",
                    name="COM LOTE",
                    lote="LOTE 1",
                    lote_valid_from=date(2026, 9, 1),
                )
                current = await session.scalar(
                    select(AnimalLotAssignment).where(
                        AnimalLotAssignment.animal_id == animal.id
                    )
                )
                assert current.lote == "LOTE 1"
                assert current.valid_from == date(2026, 9, 1)
                assert current.valid_to is None
                assert current.source == "manual"

        _run(scenario)


class TestLinkBrinco:
    def test_links_brinco_to_animal_without_one(self) -> None:
        """Destrava os 142 registros migrados sem brinco."""

        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _farm(session, "Vincular brinco")
                animal = await create_animal(
                    session,
                    farm_id=farm.id,
                    actor=ACTOR,
                    brinco=None,
                    name="MALHADINHA",
                    legacy_id="v-malhadinha",
                )
                updated = await link_brinco(
                    session,
                    animal_id=animal.id,
                    farm_id=farm.id,
                    actor=ACTOR,
                    brinco="B1-900",
                    evidence="Brinco físico conferido no curral em 18/09/2026",
                )
                assert updated.brinco == "B1-900"
                assert "animal_brinco_linked" in await _audit_actions(session, animal.id)

        _run(scenario)

    def test_records_evidence_and_previous_value_in_audit(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _farm(session, "Evidencia do brinco")
                animal = await create_animal(
                    session, farm_id=farm.id, actor=ACTOR, brinco="111", name="TROCA"
                )
                await link_brinco(
                    session,
                    animal_id=animal.id,
                    farm_id=farm.id,
                    actor=ACTOR,
                    brinco="222",
                    evidence="Brinco substituído por perda",
                )
                event = await session.scalar(
                    select(AuditEvent).where(
                        AuditEvent.entity_id == animal.id,
                        AuditEvent.action == "animal_brinco_linked",
                    )
                )
                assert event.previous_value["brinco"] == "111"
                assert event.new_value["brinco"] == "222"
                assert "perda" in event.new_value["evidence"]

        _run(scenario)

    def test_requires_evidence(self) -> None:
        """Vincular brinco muda a identidade operacional: exige justificativa."""

        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _farm(session, "Brinco sem evidencia")
                animal = await create_animal(
                    session, farm_id=farm.id, actor=ACTOR, brinco=None, name="Y"
                )
                with pytest.raises(AnimalRegistryError) as excinfo:
                    await link_brinco(
                        session,
                        animal_id=animal.id,
                        farm_id=farm.id,
                        actor=ACTOR,
                        brinco="333",
                        evidence="   ",
                    )
                assert "evidência" in str(excinfo.value).lower()

        _run(scenario)

    def test_rejects_brinco_already_used(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _farm(session, "Brinco ja usado")
                await create_animal(
                    session, farm_id=farm.id, actor=ACTOR, brinco="444", name="DONO"
                )
                other = await create_animal(
                    session, farm_id=farm.id, actor=ACTOR, brinco=None, name="OUTRO"
                )
                with pytest.raises(AnimalRegistryError):
                    await link_brinco(
                        session,
                        animal_id=other.id,
                        farm_id=farm.id,
                        actor=ACTOR,
                        brinco="444",
                        evidence="tentativa",
                    )

        _run(scenario)


class TestUpdateAnimal:
    def test_name_change_is_audited(self) -> None:
        """Nome é descritivo, mas alterá-lo é uma ação cadastral rastreável."""

        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _farm(session, "Renomear")
                animal = await create_animal(
                    session, farm_id=farm.id, actor=ACTOR, brinco="555", name="KAROLINA"
                )
                await update_animal(
                    session,
                    animal_id=animal.id,
                    farm_id=farm.id,
                    actor=ACTOR,
                    changes={"name": "Carolina"},
                )
                event = await session.scalar(
                    select(AuditEvent).where(
                        AuditEvent.entity_id == animal.id,
                        AuditEvent.action == "animal_updated",
                    )
                )
                assert event.previous_value["name"] == "KAROLINA"
                assert event.new_value["name"] == "Carolina"

        _run(scenario)

    def test_cannot_change_brinco_through_update(self) -> None:
        """Identidade só muda pelo caminho explícito, que exige evidência."""

        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _farm(session, "Update nao muda brinco")
                animal = await create_animal(
                    session, farm_id=farm.id, actor=ACTOR, brinco="666", name="Z"
                )
                with pytest.raises(AnimalRegistryError):
                    await update_animal(
                        session,
                        animal_id=animal.id,
                        farm_id=farm.id,
                        actor=ACTOR,
                        changes={"brinco": "777"},
                    )

        _run(scenario)

    def test_no_audit_event_when_nothing_changes(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _farm(session, "Sem mudanca")
                animal = await create_animal(
                    session, farm_id=farm.id, actor=ACTOR, brinco="888", name="IGUAL"
                )
                await update_animal(
                    session,
                    animal_id=animal.id,
                    farm_id=farm.id,
                    actor=ACTOR,
                    changes={"name": "IGUAL"},
                )
                assert await _audit_actions(session, animal.id) == ["animal_created"]

        _run(scenario)

    def test_rejects_animal_from_another_farm(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                one = await _farm(session, "Fazenda dona")
                other = await _farm(session, "Fazenda intrusa")
                animal = await create_animal(
                    session, farm_id=one.id, actor=ACTOR, brinco="999", name="ALVO"
                )
                with pytest.raises(AnimalRegistryError):
                    await update_animal(
                        session,
                        animal_id=animal.id,
                        farm_id=other.id,
                        actor=ACTOR,
                        changes={"name": "INVADIDO"},
                    )

        _run(scenario)


class TestAssignLot:
    def test_new_lot_closes_the_previous_period(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _farm(session, "Troca de lote cadastro")
                animal = await create_animal(
                    session,
                    farm_id=farm.id,
                    actor=ACTOR,
                    brinco="1200",
                    name="MUDOU",
                    lote="LOTE 1",
                    lote_valid_from=date(2026, 1, 1),
                )
                await assign_lot(
                    session,
                    animal_id=animal.id,
                    farm_id=farm.id,
                    actor=ACTOR,
                    lote="LOTE 2",
                    valid_from=date(2026, 6, 1),
                )
                rows = list(
                    await session.scalars(
                        select(AnimalLotAssignment)
                        .where(AnimalLotAssignment.animal_id == animal.id)
                        .order_by(AnimalLotAssignment.valid_from)
                    )
                )
                assert [r.lote for r in rows] == ["LOTE 1", "LOTE 2"]
                assert rows[0].valid_to == date(2026, 5, 31)
                assert rows[1].valid_to is None

        _run(scenario)

    def test_history_is_preserved_not_overwritten(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _farm(session, "Historico preservado")
                animal = await create_animal(
                    session,
                    farm_id=farm.id,
                    actor=ACTOR,
                    brinco="1300",
                    name="HIST",
                    lote="LOTE 1",
                    lote_valid_from=date(2026, 1, 1),
                )
                for lote, day in (("LOTE 2", date(2026, 4, 1)), ("LOTE 3", date(2026, 7, 1))):
                    await assign_lot(
                        session,
                        animal_id=animal.id,
                        farm_id=farm.id,
                        actor=ACTOR,
                        lote=lote,
                        valid_from=day,
                    )
                total = await session.scalar(
                    select(func.count())
                    .select_from(AnimalLotAssignment)
                    .where(AnimalLotAssignment.animal_id == animal.id)
                )
                assert total == 3

        _run(scenario)

    def test_rejects_start_before_current_period(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _farm(session, "Lote retroativo")
                animal = await create_animal(
                    session,
                    farm_id=farm.id,
                    actor=ACTOR,
                    brinco="1400",
                    name="RETRO",
                    lote="LOTE 1",
                    lote_valid_from=date(2026, 6, 1),
                )
                with pytest.raises(AnimalRegistryError):
                    await assign_lot(
                        session,
                        animal_id=animal.id,
                        farm_id=farm.id,
                        actor=ACTOR,
                        lote="LOTE 2",
                        valid_from=date(2026, 1, 1),
                    )

        _run(scenario)

    def test_same_lot_again_is_a_no_op(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _farm(session, "Mesmo lote")
                animal = await create_animal(
                    session,
                    farm_id=farm.id,
                    actor=ACTOR,
                    brinco="1500",
                    name="MESMO",
                    lote="LOTE 1",
                    lote_valid_from=date(2026, 1, 1),
                )
                await assign_lot(
                    session,
                    animal_id=animal.id,
                    farm_id=farm.id,
                    actor=ACTOR,
                    lote="LOTE 1",
                    valid_from=date(2026, 6, 1),
                )
                total = await session.scalar(
                    select(func.count())
                    .select_from(AnimalLotAssignment)
                    .where(AnimalLotAssignment.animal_id == animal.id)
                )
                assert total == 1

        _run(scenario)

    def test_lot_change_is_audited(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _farm(session, "Lote auditado")
                animal = await create_animal(
                    session,
                    farm_id=farm.id,
                    actor=ACTOR,
                    brinco="1600",
                    name="AUDIT",
                    lote="LOTE 1",
                    lote_valid_from=date(2026, 1, 1),
                )
                await assign_lot(
                    session,
                    animal_id=animal.id,
                    farm_id=farm.id,
                    actor=ACTOR,
                    lote="LOTE 2",
                    valid_from=date(2026, 6, 1),
                )
                assert "animal_lot_changed" in await _audit_actions(session, animal.id)

        _run(scenario)
