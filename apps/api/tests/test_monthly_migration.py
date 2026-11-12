"""Snapshot inicial tem vigência de hoje e migração é reversível sem tocar a base."""
import asyncio
import sys
import asyncpg
from tests.test_tenant_migration import migration_database, command


def test_history_migration_seeds_only_known_current_values(migration_database):
    env = migration_database
    command([sys.executable, '-m', 'alembic', 'upgrade', '0019_single_farm_per_user'], env)

    async def seed():
        db = await asyncpg.connect(env['POSTGRES_URL'].replace('postgresql+asyncpg', 'postgresql'))
        try:
            farm = await db.fetchval("INSERT INTO farms(name,timezone,milk_price_per_liter) VALUES ('Anterior','America/Recife',2.5) RETURNING id")
            supply = await db.fetchval("INSERT INTO supplies(farm_id,name,price_per_kg) VALUES ($1,'Silagem',0.5) RETURNING id", farm)
            await db.execute("INSERT INTO supply_diets(supply_id,lote,kg_per_day) VALUES ($1,'LOTE 1',40)", supply)
            return farm, supply
        finally:
            await db.close()

    farm, supply = asyncio.run(seed())
    command([sys.executable, '-m', 'alembic', 'upgrade', 'head'], env)

    async def inspect():
        db = await asyncpg.connect(env['POSTGRES_URL'].replace('postgresql+asyncpg', 'postgresql'))
        try:
            assert await db.fetchval("SELECT count(*) FROM milk_price_history WHERE farm_id=$1 AND source='snapshot' AND effective_on=(CURRENT_TIMESTAMP AT TIME ZONE 'America/Recife')::date", farm) == 1
            assert await db.fetchval("SELECT count(*) FROM supply_diet_history WHERE supply_id=$1 AND source='snapshot' AND kg_per_day=40 AND effective_on=(CURRENT_TIMESTAMP AT TIME ZONE 'America/Recife')::date", supply) == 1
            assert await db.fetchval('SELECT milk_price_per_liter FROM farms WHERE id=$1', farm) == 2.5
        finally:
            await db.close()
    asyncio.run(inspect())
    command([sys.executable, '-m', 'alembic', 'downgrade', '-1'], env)
    command([sys.executable, '-m', 'alembic', 'upgrade', 'head'], env)
    asyncio.run(inspect())
