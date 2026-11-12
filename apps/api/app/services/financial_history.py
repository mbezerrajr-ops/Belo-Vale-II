"""Gravações temporais; editar um período antigo preserva o valor mais recente."""
from datetime import date
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Farm, MilkPriceHistory, SupplyDiet, SupplyDietHistory


async def record_milk_price(session: AsyncSession, farm: Farm, price: float | None, effective: date, actor: str):
    await session.execute(insert(MilkPriceHistory).values(farm_id=farm.id, effective_on=effective, price_per_liter=price, recorded_by=actor, source='manual')
        .on_conflict_do_update(index_elements=['farm_id', 'effective_on'], set_={'price_per_liter': price, 'recorded_by': actor, 'source': 'manual', 'updated_at': func.now()}))
    await session.flush()
    latest = await session.scalar(select(MilkPriceHistory).where(MilkPriceHistory.farm_id == farm.id).order_by(MilkPriceHistory.effective_on.desc()).limit(1))
    farm.milk_price_per_liter = latest.price_per_liter


async def record_diet(session: AsyncSession, diet: SupplyDiet, kg: float, effective: date, actor: str):
    await session.execute(insert(SupplyDietHistory).values(supply_id=diet.supply_id, lote=diet.lote, effective_on=effective, kg_per_day=kg, recorded_by=actor, source='manual')
        .on_conflict_do_update(index_elements=['supply_id', 'lote', 'effective_on'], set_={'kg_per_day': kg, 'recorded_by': actor, 'source': 'manual', 'updated_at': func.now()}))
    await session.flush()
    latest = await session.scalar(select(SupplyDietHistory).where(SupplyDietHistory.supply_id == diet.supply_id, SupplyDietHistory.lote == diet.lote).order_by(SupplyDietHistory.effective_on.desc()).limit(1))
    diet.kg_per_day = latest.kg_per_day
