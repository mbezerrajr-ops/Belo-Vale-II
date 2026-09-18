"""Indicadores do painel do rebanho.

Portam o que a plataforma legada calculava, sobre os dados agora no banco. As
fórmulas são as mesmas, e os testes fixam justamente isso: custo do lote é a
soma de dieta × preço, custo por vaca é o custo do lote dividido pelas vacas
daquele lote, e receita é produção × preço do leite.
"""

import asyncio
import os
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.models import (
    Animal,
    AnimalLotAssignment,
    BaselineImport,
    Farm,
    OfficialMeasurement,
    Supply,
    SupplyDiet,
)
from app.services.dashboard import build_dashboard, lactation_stage


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


async def _scenario_farm(session: AsyncSession, name: str) -> Farm:
    """Fazenda pequena e previsível: dois lotes, quatro vacas, um insumo."""
    farm = Farm(name=name, milk_price_per_liter=Decimal("2.59"))
    session.add(farm)
    await session.commit()

    baseline = BaselineImport(
        farm_id=farm.id,
        source_path="teste",
        source_sha256="0" * 64,
        animal_count=4,
        measurement_count=3,
        approved_by="titular",
        approved_at=date(2026, 8, 25),
    )
    session.add(baseline)

    silagem = Supply(
        farm_id=farm.id, name="Silagem", price_per_kg=Decimal("0.50"), legacy_id="s1"
    )
    session.add(silagem)
    await session.flush()
    session.add_all(
        [
            SupplyDiet(supply_id=silagem.id, lote="LOTE 1", kg_per_day=Decimal("100")),
            SupplyDiet(supply_id=silagem.id, lote="LOTE 2", kg_per_day=Decimal("40")),
        ]
    )

    especificacao = [
        ("a1", "AURORA", "LOTE 1", "Em lactação", date(2026, 6, 1), Decimal("30")),
        ("a2", "BONITA", "LOTE 1", "Em lactação", date(2026, 1, 10), Decimal("20")),
        ("a3", "CIGANA", "LOTE 2", "Seca", None, None),
        ("a4", "DALIA", None, "Em lactação", date(2026, 8, 1), Decimal("10")),
    ]
    for brinco, nome, lote, situacao, parto, producao in especificacao:
        animal = Animal(
            farm_id=farm.id,
            identifier=brinco,
            brinco=brinco,
            name=nome,
            situacao=situacao,
            status="Ativo",
            ultimo_parto=parto,
        )
        session.add(animal)
        await session.flush()
        if lote:
            session.add(
                AnimalLotAssignment(
                    animal_id=animal.id,
                    lote=lote,
                    valid_from=date(2026, 1, 1),
                    source="manual",
                )
            )
        if producao is not None:
            session.add(
                OfficialMeasurement(
                    animal_id=animal.id,
                    measured_on=date(2026, 8, 25),
                    values={"producao": float(producao)},
                    status="active",
                    provenance="legacy_baseline",
                    baseline_import_id=baseline.id,
                    reviewed_by="titular",
                    lote_observado=lote,
                )
            )
    await session.commit()
    return farm


class TestHerdComposition:
    def test_counts_animals_by_situation(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _scenario_farm(session, "Composição")
                panel = await build_dashboard(session, farm_id=farm.id)

                assert panel.total_animals == 4
                assert panel.by_situation["Em lactação"] == 3
                assert panel.by_situation["Seca"] == 1

        _run(scenario)

    def test_counts_animals_without_a_lot(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _scenario_farm(session, "Sem lote")
                panel = await build_dashboard(session, farm_id=farm.id)

                assert panel.animals_without_lot == 1

        _run(scenario)


class TestLotComparison:
    def test_feed_cost_is_diet_times_price(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _scenario_farm(session, "Custo do lote")
                panel = await build_dashboard(session, farm_id=farm.id)

                lot1 = next(l for l in panel.lots if l.lote == "LOTE 1")
                lot2 = next(l for l in panel.lots if l.lote == "LOTE 2")
                assert lot1.feed_cost == pytest.approx(50.0)  # 100 kg × 0,50
                assert lot2.feed_cost == pytest.approx(20.0)  # 40 kg × 0,50

        _run(scenario)

    def test_cost_per_cow_divides_the_lot_cost(self) -> None:
        """A dieta é por lote, então o custo por vaca é uma divisão."""

        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _scenario_farm(session, "Custo por vaca")
                panel = await build_dashboard(session, farm_id=farm.id)

                lot1 = next(l for l in panel.lots if l.lote == "LOTE 1")
                assert lot1.animals == 2
                assert lot1.cost_per_animal == pytest.approx(25.0)

        _run(scenario)

    def test_revenue_uses_the_milk_price(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _scenario_farm(session, "Receita")
                panel = await build_dashboard(session, farm_id=farm.id)

                lot1 = next(l for l in panel.lots if l.lote == "LOTE 1")
                assert lot1.production == pytest.approx(50.0)  # 30 + 20
                assert lot1.revenue == pytest.approx(50.0 * 2.59)
                assert lot1.profit == pytest.approx(50.0 * 2.59 - 50.0)

        _run(scenario)

    def test_cost_ratio_is_zero_when_there_is_no_revenue(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _scenario_farm(session, "Sem receita")
                panel = await build_dashboard(session, farm_id=farm.id)

                lot2 = next(l for l in panel.lots if l.lote == "LOTE 2")
                assert lot2.production == pytest.approx(0.0)
                assert lot2.cost_ratio == 0.0

        _run(scenario)


class TestTotals:
    def test_totals_sum_the_lots(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _scenario_farm(session, "Totais")
                panel = await build_dashboard(session, farm_id=farm.id)

                assert panel.total_feed_cost == pytest.approx(70.0)
                # A produção total inclui a vaca sem lote.
                assert panel.total_production == pytest.approx(60.0)
                assert panel.total_revenue == pytest.approx(60.0 * 2.59)

        _run(scenario)

    def test_reports_the_measurement_date_used(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _scenario_farm(session, "Data de referência")
                panel = await build_dashboard(session, farm_id=farm.id)

                assert panel.measured_on == date(2026, 8, 25)

        _run(scenario)

    def test_production_series_by_date(self) -> None:
        """Alimenta o gráfico de tendência: total e cobertura por coleta."""

        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _scenario_farm(session, "Série por data")
                panel = await build_dashboard(session, farm_id=farm.id)

                assert [
                    (p.measured_on, p.liters, p.animals) for p in panel.production_by_date
                ] == [(date(2026, 8, 25), 60.0, 3)]

        _run(scenario)

    def test_available_dates_are_listed(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _scenario_farm(session, "Datas disponíveis")
                panel = await build_dashboard(session, farm_id=farm.id)

                assert panel.available_dates == [date(2026, 8, 25)]

        _run(scenario)


class TestProductionRanking:
    def test_ranks_top_and_bottom_producers(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _scenario_farm(session, "Ranking")
                panel = await build_dashboard(session, farm_id=farm.id)

                assert [p.name for p in panel.top_producers][:1] == ["AURORA"]
                assert [p.name for p in panel.bottom_producers][:1] == ["DALIA"]

        _run(scenario)

    def test_ranking_ignores_animals_without_a_reading(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _scenario_farm(session, "Ranking sem leitura")
                panel = await build_dashboard(session, farm_id=farm.id)

                assert "CIGANA" not in [p.name for p in panel.top_producers]
                assert "CIGANA" not in [p.name for p in panel.bottom_producers]

        _run(scenario)


class TestFeedBreakdown:
    def test_breaks_the_cost_down_by_supply(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _scenario_farm(session, "Composição do custo")
                panel = await build_dashboard(session, farm_id=farm.id)

                silagem = next(s for s in panel.feed_breakdown if s.name == "Silagem")
                assert silagem.cost_by_lot["LOTE 1"] == pytest.approx(50.0)
                assert silagem.total_cost == pytest.approx(70.0)

        _run(scenario)


class TestLactationStage:
    """DEL derivado do último parto, nunca persistido."""

    def test_classifies_by_days_in_milk(self) -> None:
        reference = date(2026, 8, 25)
        assert lactation_stage(date(2026, 8, 1), reference) == "0-100"
        assert lactation_stage(date(2026, 6, 1), reference) == "0-100"
        assert lactation_stage(date(2026, 1, 10), reference) == "201-305"
        assert lactation_stage(date(2025, 1, 10), reference) == "305+"

    def test_without_a_calving_date_there_is_no_stage(self) -> None:
        assert lactation_stage(None, date(2026, 8, 25)) is None

    def test_groups_animals_by_stage(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _scenario_farm(session, "Estágio")
                panel = await build_dashboard(session, farm_id=farm.id)

                assert panel.lactation_stages["0-100"] == 2  # AURORA e DALIA
                assert panel.lactation_stages["201-305"] == 1  # BONITA

        _run(scenario)


class TestFilters:
    def test_filters_by_lot(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _scenario_farm(session, "Filtro de lote")
                panel = await build_dashboard(session, farm_id=farm.id, lote="LOTE 1")

                assert panel.total_animals == 2
                assert panel.total_production == pytest.approx(50.0)

        _run(scenario)

    def test_filters_by_situation(self) -> None:
        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _scenario_farm(session, "Filtro de situação")
                panel = await build_dashboard(
                    session, farm_id=farm.id, situacao="Seca"
                )

                assert panel.total_animals == 1

        _run(scenario)


class TestMissingConfiguration:
    def test_without_a_milk_price_revenue_is_unavailable(self) -> None:
        """Melhor não mostrar receita do que inventar um preço."""

        async def scenario(factory) -> None:
            async with factory() as session:
                farm = await _scenario_farm(session, "Sem preço do leite")
                farm.milk_price_per_liter = None
                await session.commit()

                panel = await build_dashboard(session, farm_id=farm.id)

                assert panel.milk_price is None
                assert panel.total_revenue is None
                lot1 = next(l for l in panel.lots if l.lote == "LOTE 1")
                assert lot1.revenue is None
                assert lot1.profit is None

        _run(scenario)
