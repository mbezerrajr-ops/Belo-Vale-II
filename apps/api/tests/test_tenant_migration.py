"""Ensaio real: schema antigo + baseline inteira → vários produtores.

Usa banco descartável próprio e o código versionado anterior à ampliação para
montar a origem, sem depender dos modelos novos para simular dados antigos.
"""

import asyncio
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy.engine import make_url


ROOT = Path(__file__).resolve().parents[3]
API = ROOT / "apps" / "api"
CANONICAL = (
    ROOT / "belo-vale-ii-projeto-completo" / "plataforma" / "state_canonical.json"
)


def command(args, env, cwd=API):
    result = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    return result.stdout


@pytest.fixture
def migration_database():
    raw = os.getenv("POSTGRES_URL")
    if not raw or not (ROOT / ".git").exists():
        pytest.skip("PostgreSQL e histórico Git são necessários ao ensaio de migração")
    original = make_url(raw)
    name = "bv_migration_" + uuid4().hex

    async def execute(sql):
        connection = await asyncpg.connect(
            original.set(drivername="postgresql").render_as_string(hide_password=False)
        )
        try:
            await connection.execute(sql)
        finally:
            await connection.close()

    asyncio.run(execute(f'CREATE DATABASE "{name}"'))
    env = {
        **os.environ,
        "POSTGRES_URL": original.set(database=name).render_as_string(
            hide_password=False
        ),
        "PYTHONIOENCODING": "utf-8",
    }
    try:
        command(
            [sys.executable, "-m", "alembic", "upgrade", "0016_measurement_note"], env
        )
        yield env
    finally:
        asyncio.run(execute(f'DROP DATABASE "{name}" WITH (FORCE)'))


def test_entire_legacy_baseline_and_team_survive_migration(migration_database):
    env = migration_database
    with tempfile.TemporaryDirectory() as temporary:
        archive = subprocess.run(
            ["git", "archive", "e6a21da", "apps/api/app"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        ).stdout
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            bundle.extractall(temporary, filter="data")
        source_env = {**env, "PYTHONPATH": str(Path(temporary) / "apps" / "api")}
        script = """
import asyncio
from pathlib import Path
from datetime import date
from app.db.models import Farm, User
from app.db.session import get_session_factory
from app.core.security import hash_password
from app.services.baseline_snapshot import parse_baseline
from app.services.baseline_importer import import_baseline
async def main():
    async with get_session_factory()() as session:
        farm=Farm(name='Belo Vale II')
        session.add(farm)
        for role in ['admin','operator']:
            session.add(User(email=role+'@migration.test',password_hash=hash_password('capim da migração conferida'),role=role,is_active=True))
        await session.commit()
        snapshot=parse_baseline(Path(CANONICAL_PATH).read_text(encoding='utf-8'))
        report=await import_baseline(session,snapshot,farm_id=farm.id,approved_by='admin@migration.test',reference_date=date(2026,8,25),source_path='canonical',dry_run=False)
        assert not report.errors
asyncio.run(main())
""".replace("CANONICAL_PATH", repr(str(CANONICAL)))
        command([sys.executable, "-c", script], source_env, cwd=temporary)

    async def snapshot():
        connection = await asyncpg.connect(
            env["POSTGRES_URL"].replace("postgresql+asyncpg", "postgresql")
        )
        try:
            result = {}
            for table in [
                "farms",
                "users",
                "animals",
                "official_measurements",
                "baseline_imports",
                "animal_lot_assignments",
                "supplies",
                "supply_prices",
                "supply_diets",
                "audit_events",
            ]:
                rows = await connection.fetch(
                    f'SELECT to_jsonb(t) AS row FROM "{table}" t ORDER BY id'
                )
                normalized = [json.loads(row["row"]) for row in rows]
                for row in normalized:
                    for column in [
                        "updated_at",
                        "producer_account_id",
                        "timezone",
                        "lot_settings",
                        "email_verified_at",
                        "email_verification_required",
                        "is_platform_admin",
                    ]:
                        row.pop(column, None)
                result[table] = normalized
            return result
        finally:
            await connection.close()

    before = asyncio.run(snapshot())
    assert len(before["animals"]) == 401 and len(before["official_measurements"]) == 152
    command([sys.executable, "-m", "alembic", "upgrade", "head"], env)
    assert asyncio.run(snapshot()) == before

    async def memberships():
        connection = await asyncpg.connect(
            env["POSTGRES_URL"].replace("postgresql+asyncpg", "postgresql")
        )
        try:
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM producer_memberships WHERE role='owner'"
                )
                == 1
            )
            assert (
                await connection.fetchval("SELECT count(*) FROM farm_memberships") == 2
            )
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM farms WHERE producer_account_id IS NULL"
                )
                == 0
            )
        finally:
            await connection.close()

    asyncio.run(memberships())
    command(
        [sys.executable, "-m", "alembic", "downgrade", "0016_measurement_note"], env
    )
    assert asyncio.run(snapshot()) == before


def test_ambiguous_legacy_ownership_aborts_without_partial_migration(
    migration_database,
):
    env = migration_database

    async def prepare():
        connection = await asyncpg.connect(
            env["POSTGRES_URL"].replace("postgresql+asyncpg", "postgresql")
        )
        try:
            await connection.execute(
                "INSERT INTO farms(name) VALUES('Primeira'),('Segunda')"
            )
        finally:
            await connection.close()

    asyncio.run(prepare())
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=API,
        env=env,
        capture_output=True,
    )
    assert result.returncode != 0

    async def verify():
        connection = await asyncpg.connect(
            env["POSTGRES_URL"].replace("postgresql+asyncpg", "postgresql")
        )
        try:
            assert (
                await connection.fetchval("SELECT version_num FROM alembic_version")
                == "0016_measurement_note"
            )
            assert await connection.fetchval("SELECT count(*) FROM farms") == 2
            assert (
                await connection.fetchval("SELECT to_regclass('producer_accounts')")
                is None
            )
        finally:
            await connection.close()

    asyncio.run(verify())


def test_single_farm_migration_preserves_ambiguous_existing_links(migration_database):
    env = migration_database
    command([sys.executable, "-m", "alembic", "upgrade", "0018_farm_integrity"], env)

    async def prepare():
        connection = await asyncpg.connect(
            env["POSTGRES_URL"].replace("postgresql+asyncpg", "postgresql")
        )
        try:
            user = await connection.fetchval(
                "INSERT INTO users(email,password_hash,role) VALUES ('ambiguous@example.org','not-a-login-hash','admin') RETURNING id"
            )
            farms = await connection.fetch(
                "INSERT INTO farms(name) VALUES ('Primeira'),('Segunda') RETURNING id"
            )
            for farm in farms:
                await connection.execute(
                    "INSERT INTO farm_memberships(farm_id,user_id,role) VALUES ($1,$2,'admin')",
                    farm["id"],
                    user,
                )
        finally:
            await connection.close()

    asyncio.run(prepare())
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=API,
        env=env,
        capture_output=True,
    )
    assert result.returncode != 0

    async def verify():
        connection = await asyncpg.connect(
            env["POSTGRES_URL"].replace("postgresql+asyncpg", "postgresql")
        )
        try:
            assert (
                await connection.fetchval("SELECT version_num FROM alembic_version")
                == "0018_farm_integrity"
            )
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM farm_memberships WHERE is_active"
                )
                == 2
            )
            assert await connection.fetchval("SELECT count(*) FROM farms") == 2
        finally:
            await connection.close()

    asyncio.run(verify())
