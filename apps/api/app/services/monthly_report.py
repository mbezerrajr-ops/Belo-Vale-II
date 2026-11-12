"""Fechamento estimado: média das coletas × dias, com cobertura temporal explícita."""
from bisect import bisect_right
from calendar import monthrange
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Animal, AnimalLotAssignment, Farm, OfficialMeasurement, Supply, SupplyDiet, SupplyDietHistory, SupplyPrice, MilkPriceHistory
from app.schemas.monthly_report import MonthlyReport, MonthResult
from app.services.dashboard import _producao

MISSING = object()
METHOD = ('Produção estimada = média dos totais das coletas do mês × dias do período. '
          'A média por animal considera cada leitura individual. Receita usa essa produção diária estimada '
          'e o preço do leite vigente; alimentação soma as dietas e preços vigentes por dia. '
          'Não inclui outras despesas da fazenda. Meses sem coleta não recebem produção inventada.')


def dec(value):
    return Decimal(str(value))


def rounded(value):
    return None if value is None else float(value.quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def month_date(value: str) -> date:
    if len(value) != 7 or value[4] != '-':
        raise ValueError('Informe o mês no formato AAAA-MM.')
    return date.fromisoformat(value + '-01')


def month_keys(start: str, end: str, today: date):
    first, last = month_date(start), month_date(end)
    count = (last.year - first.year) * 12 + last.month - first.month + 1
    if not 1 <= count <= 24:
        raise ValueError('Escolha um intervalo de 1 a 24 meses, em ordem cronológica.')
    if last > today.replace(day=1):
        raise ValueError('O mês final não pode estar no futuro.')
    return [date(first.year + (first.month - 1 + i) // 12, (first.month - 1 + i) % 12 + 1, 1) for i in range(count)]


class Timeline:
    def __init__(self, rows):
        values = sorted(rows, key=lambda row: row[0])
        self.days = [row[0] for row in values]
        self.values = [row[1] for row in values]

    def on(self, day):
        index = bisect_right(self.days, day) - 1
        return self.values[index] if index >= 0 else MISSING


async def build_monthly_report(session: AsyncSession, farm: Farm, start: str, end: str, today: date, simulate_current=False) -> MonthlyReport:
    keys = month_keys(start, end, today)
    finish = min(today, keys[-1].replace(day=monthrange(keys[-1].year, keys[-1].month)[1]))
    readings = (await session.execute(select(OfficialMeasurement).join(Animal, Animal.id == OfficialMeasurement.animal_id).where(
        Animal.farm_id == farm.id, OfficialMeasurement.status == 'active',
        OfficialMeasurement.measured_on >= keys[0], OfficialMeasurement.measured_on <= finish,
    ))).scalars().all()
    assignments = (await session.execute(select(AnimalLotAssignment).join(Animal, Animal.id == AnimalLotAssignment.animal_id).where(
        Animal.farm_id == farm.id, AnimalLotAssignment.kind == 'diet', AnimalLotAssignment.valid_from <= finish,
        or_(AnimalLotAssignment.valid_to.is_(None), AnimalLotAssignment.valid_to >= keys[0]),
    ))).scalars().all()
    supplies = list(await session.scalars(select(Supply).where(Supply.farm_id == farm.id)))
    current_diets = list(await session.scalars(select(SupplyDiet).join(Supply).where(Supply.farm_id == farm.id)))
    prices = list(await session.scalars(select(SupplyPrice).join(Supply).where(Supply.farm_id == farm.id)))
    diets = list(await session.scalars(select(SupplyDietHistory).join(Supply).where(Supply.farm_id == farm.id)))
    milk = list(await session.scalars(select(MilkPriceHistory).where(MilkPriceHistory.farm_id == farm.id)))
    milk_line = Timeline([(r.effective_on, None if r.price_per_liter is None else dec(r.price_per_liter)) for r in milk])
    price_rows, diet_rows = defaultdict(list), defaultdict(list)
    for row in prices:
        price_rows[row.supply_id].append((row.effective_on, dec(row.price_per_kg)))
    for row in diets:
        diet_rows[(row.supply_id, row.lote)].append((row.effective_on, dec(row.kg_per_day)))
    price_lines = {key: Timeline(rows) for key, rows in price_rows.items()}
    diet_lines = {key: Timeline(rows) for key, rows in diet_rows.items()}
    current_kg = {(row.supply_id, row.lote): dec(row.kg_per_day) for row in current_diets}
    current_prices = {s.id: dec(s.price_per_kg) for s in supplies}
    all_pairs = set(diet_lines) | set(current_kg)
    by_month = defaultdict(list)
    for row in readings:
        by_month[row.measured_on.strftime('%Y-%m')].append(row)
    results = []
    for first in keys:
        last = first.replace(day=monthrange(first.year, first.month)[1])
        stop = min(last, today)
        days = (stop - first).days + 1
        month = first.strftime('%Y-%m')
        observations = by_month[month]
        daily = defaultdict(Decimal)
        animal_counts = defaultdict(int)
        observed_lots, unassigned = set(), set()
        for reading in observations:
            daily[reading.measured_on] += dec(_producao(reading.values or {}))
            animal_counts[reading.measured_on] += 1
            lot = reading.lote_observado or next((a.lote for a in assignments if a.animal_id == reading.animal_id and a.valid_from <= reading.measured_on and (a.valid_to is None or a.valid_to >= reading.measured_on)), None)
            if lot:
                observed_lots.add(lot)
            else:
                unassigned.add(reading.animal_id)
        total = sum(daily.values(), Decimal(0))
        average = total / len(daily) if daily else None
        revenue_sum = cost_sum = Decimal(0)
        milk_days = diet_days = assumed_days = 0
        missing_lots = set()
        for offset in range(days):
            day = first + timedelta(days=offset)
            assumed = False
            milk_price = milk_line.on(day)
            if milk_price is MISSING or milk_price is None:
                if simulate_current and farm.milk_price_per_liter is not None:
                    milk_price = dec(farm.milk_price_per_liter)
                    assumed = True
            if milk_price is not MISSING and milk_price is not None:
                milk_days += 1
                if average is not None:
                    revenue_sum += average * milk_price
            needed = {a.lote for a in assignments if a.valid_from <= day and (a.valid_to is None or a.valid_to >= day)} or set(observed_lots)
            quantities = {}
            for pair in all_pairs:
                quantity = diet_lines[pair].on(day) if pair in diet_lines else MISSING
                if quantity is MISSING and simulate_current and pair in current_kg:
                    quantity = current_kg[pair]
                    assumed = True
                if quantity is not MISSING:
                    quantities[pair] = quantity
                    needed.add(pair[1])
            known_lots = {pair[1] for pair in quantities}
            missing_lots.update(needed - known_lots)
            cost_known = bool(needed) and needed <= known_lots and not unassigned
            day_cost = Decimal(0)
            for (supply_id, _), kg in quantities.items():
                if not kg:
                    continue  # Zero cadastrado não precisa de preço para custar zero.
                price = price_lines[supply_id].on(day) if supply_id in price_lines else MISSING
                if price is MISSING and simulate_current:
                    price = current_prices[supply_id]
                    assumed = True
                if price is MISSING:
                    cost_known = False
                else:
                    day_cost += kg * price
            if cost_known:
                diet_days += 1
                cost_sum += day_cost
            assumed_days += int(assumed)
        revenue = revenue_sum if milk_days == days and average is not None else None
        cost = cost_sum if diet_days == days else None
        result = revenue - cost if revenue is not None and cost is not None else None
        warnings = []
        if not daily:
            warnings.append('Sem coletas neste mês; não há base para estimar produção ou resultado.')
        elif len(daily) < days:
            warnings.append(f'Estimativa baseada em {len(daily)} dia(s) de coleta para {days} dias do período; os dias sem coleta não foram medidos.')
        if len(set(animal_counts.values())) > 1:
            warnings.append('As coletas têm quantidades diferentes de animais; essa variação pode afetar a estimativa.')
        if milk_days < days:
            warnings.append(f'Preço do leite sem histórico em {days - milk_days} dia(s).')
        if diet_days < days:
            warnings.append(f'Alimentação sem base completa em {days - diet_days} dia(s).')
        if missing_lots:
            warnings.append('Lotes sem dieta vigente: ' + ', '.join(sorted(missing_lots)) + '.')
        if unassigned:
            warnings.append(f'{len(unassigned)} animal(is) com leitura sem lote de ordenha identificado na data.')
        if assumed_days:
            warnings.append(f'Simulação: valores atuais substituem histórico ausente em {assumed_days} dia(s).')
        if stop < last:
            warnings.append('Mês em andamento: considera somente os dias até hoje e não entra no melhor/pior mês.')
        row = MonthResult(month=month, start=first, end=stop, elapsed_days=days, calendar_days=last.day, in_progress=stop < last,
            reading_days=len(daily), reading_count=len(observations), animals_read=len({r.animal_id for r in observations}),
            animals_per_collection_min=min(animal_counts.values()) if animal_counts else None,
            animals_per_collection_max=max(animal_counts.values()) if animal_counts else None,
            recorded_liters=rounded(total), average_liters_per_collection=rounded(average),
            average_liters_per_animal_reading=rounded(total / len(observations)) if observations else None,
            estimated_liters=rounded(average * days) if average is not None else None,
            estimated_revenue=rounded(revenue), estimated_feed_cost=rounded(cost), estimated_result=rounded(result),
            margin_pct=rounded(result / revenue * 100) if result is not None and revenue > 0 else None,
            status='insufficient' if result is None else 'positive' if rounded(result) > 0 else 'negative' if rounded(result) < 0 else 'balanced',
            milk_price_days=milk_days, diet_days=diet_days, assumed_days=assumed_days, warnings=warnings)
        if results:
            previous = results[-1]
            if row.estimated_liters is not None and previous.estimated_liters:
                row.production_change_pct = rounded((dec(row.estimated_liters) / dec(previous.estimated_liters) - 1) * 100)
            if row.estimated_result is not None and previous.estimated_result is not None:
                row.result_change = rounded(dec(row.estimated_result) - dec(previous.estimated_result))
        results.append(row)
    comparable = [r for r in results if not r.in_progress and r.estimated_result is not None]
    return MonthlyReport(generated_on=today, farm_name=farm.name, start_month=start, end_month=end,
        current_values_simulation=simulate_current, method=METHOD, months=results,
        best_month=max(comparable, key=lambda r: r.estimated_result).month if comparable else None,
        worst_month=min(comparable, key=lambda r: r.estimated_result).month if comparable else None,
        positive_months=sum(r.status == 'positive' and not r.in_progress for r in results),
        negative_months=sum(r.status == 'negative' and not r.in_progress for r in results),
        balanced_months=sum(r.status == 'balanced' and not r.in_progress for r in results),
        insufficient_months=sum(r.status == 'insufficient' for r in results))
