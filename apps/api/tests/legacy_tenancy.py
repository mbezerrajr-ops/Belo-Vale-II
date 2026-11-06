"""Dados de vínculo explícitos para os cenários antigos de uma operação.

Os novos testes de produtores não usam este helper: criam as contas e os
vínculos através das APIs e verificam separação entre clientes.
"""

import asyncio
import os
import json
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool


async def grant_in_session(session, preferred_farm_id=None):
    from app.services.lot_kind import DIET_LOTS, MANAGEMENT_GROUPS

    lots = json.dumps(
        [{"name": name, "kind": "diet"} for name in sorted(DIET_LOTS)]
        + [{"name": name, "kind": "management"} for name in sorted(MANAGEMENT_GROUPS)]
    )
    farms = (
        (
            await session.execute(
                text("SELECT id FROM farms WHERE producer_account_id IS NULL")
            )
        )
        .scalars()
        .all()
    )
    for farm_id in farms:
        account = (
            await session.execute(
                text(
                    "INSERT INTO producer_accounts(name) VALUES ('Operação de teste') RETURNING id"
                )
            )
        ).scalar_one()
        await session.execute(
            text(
                "UPDATE farms SET producer_account_id=:a, lot_settings=CAST(:lots AS jsonb) WHERE id=:f"
            ),
            {"a": account, "f": farm_id, "lots": lots},
        )
    await session.execute(
        text("""INSERT INTO farm_memberships(farm_id,user_id,role,is_active)
      SELECT COALESCE(CAST(:preferred_farm_id AS uuid),(SELECT id FROM farms ORDER BY created_at,id LIMIT 1)),u.id,u.role,u.is_active FROM users u
      WHERE EXISTS (SELECT 1 FROM farms)
        AND NOT EXISTS (SELECT 1 FROM farm_memberships m WHERE m.user_id=u.id)
      ON CONFLICT (farm_id,user_id) DO NOTHING"""),
        {"preferred_farm_id": preferred_farm_id},
    )
    await session.execute(
        text(
            "UPDATE users SET email_verified_at=CURRENT_TIMESTAMP WHERE email_verified_at IS NULL"
        )
    )


def grant_legacy_memberships():
    async def run():
        engine = create_async_engine(os.environ["POSTGRES_URL"], poolclass=NullPool)
        try:
            async with engine.begin() as session:
                await grant_in_session(session)
        finally:
            await engine.dispose()

    asyncio.run(run())
