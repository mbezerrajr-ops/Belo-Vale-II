"""CLI de recuperação seletiva. Origem e destino são instalações separadas.

RESTORE_SOURCE_POSTGRES_URL e RESTORE_SOURCE_MINIO_* vêm do ambiente da cópia
isolada. Sem --apply, somente confere a origem e mostra as contagens.
"""

import argparse
import asyncio
import json
import os
from uuid import UUID

from app.db.session import get_session_factory
from app.services.farm_recovery import farm_snapshot, recover_farm
from app.services.storage import MinioObjectStorage, get_object_storage
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def run(args):
    engine = create_async_engine(os.environ["RESTORE_SOURCE_POSTGRES_URL"])
    source_storage = MinioObjectStorage(
        endpoint=os.environ["RESTORE_SOURCE_MINIO_URL"],
        access_key=os.environ["RESTORE_SOURCE_MINIO_ACCESS_KEY"],
        secret_key=os.environ["RESTORE_SOURCE_MINIO_SECRET_KEY"],
        bucket=os.environ.get("RESTORE_SOURCE_MINIO_BUCKET", "sheets"),
    )
    try:
        async with async_sessionmaker(engine)() as source:
            snapshot, media = await farm_snapshot(source, args.farm_id, source_storage)
        async with get_session_factory()() as target:
            result = await recover_farm(
                target, snapshot, media, get_object_storage(), apply=args.apply
            )
        print(json.dumps(result))
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(
        description="Recupera uma fazenda como cópia nova, preservando outras operações."
    )
    parser.add_argument("--farm-id", type=UUID, required=True)
    parser.add_argument("--apply", action="store_true")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
