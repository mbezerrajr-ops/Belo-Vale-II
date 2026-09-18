"""Carrega uma extração em JSON para a caixa de revisão.

Uso::

    uv run python -m app.core.load_proposals --email revisor@fazenda \\
        --file extracao.json --kind photo --label "caderno de 25/08"

O arquivo segue o formato de `EventExtraction.to_raw` (veja
`app/services/event_extraction.py`). Cada evento vira uma proposta pendente;
nada entra no rebanho sem aprovação na caixa de revisão.

Serve para duas coisas: demonstrar a caixa sem leitor real, e depurar os
leitores de foto e áudio das próximas fases — a saída deles vai para um
arquivo e entra por esta mesma porta.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.db.models import Farm, User
from app.services.event_extraction import ExtractionFormatError, extraction_from_dict
from app.services.event_proposals import SOURCE_KINDS, create_proposals


class LoadError(Exception):
    """Carga recusada. A mensagem vai para o terminal."""


async def _load(email: str, path: Path, kind: str, label: str) -> int:
    try:
        # "-" lê da entrada padrão: útil para mandar a extração para dentro
        # de um contêiner sem copiar arquivo.
        text = sys.stdin.read() if str(path) == "-" else path.read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, json.JSONDecodeError) as error:
        raise LoadError(f"Não foi possível ler {path}: {error}") from error
    try:
        extraction = extraction_from_dict(data)
    except ExtractionFormatError as error:
        raise LoadError(str(error)) from error

    settings = get_settings()
    if not settings.postgres_url:
        raise LoadError("POSTGRES_URL não configurada.")
    engine = create_async_engine(settings.postgres_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            user = await session.scalar(
                select(User).where(func.lower(User.email) == email.strip().lower(), User.is_active)
            )
            if user is None:
                raise LoadError(f"Nenhuma conta ativa com o e-mail {email}.")
            farms = list(await session.scalars(select(Farm)))
            if len(farms) != 1:
                raise LoadError(
                    "A carga exige exatamente uma fazenda cadastrada (operação monofazenda)."
                )
            await create_proposals(
                session,
                farm_id=farms[0].id,
                user=user,
                kind=kind,
                label=label or ("leitura" if str(path) == "-" else path.name),
                extraction=extraction,
            )
            await session.commit()
    finally:
        await engine.dispose()
    return len(extraction.events)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--email", required=True, help="Conta que registra a leitura.")
    parser.add_argument(
        "--file", required=True, type=Path, help="Extração em JSON ('-' para ler da entrada padrão)."
    )
    parser.add_argument("--kind", default="text", choices=SOURCE_KINDS)
    parser.add_argument("--label", default="", help="Nome exibido na caixa de revisão.")
    args = parser.parse_args(argv)

    try:
        count = asyncio.run(_load(args.email, args.file, args.kind, args.label))
    except LoadError as error:
        print(f"erro: {error}", file=sys.stderr)
        return 2
    print(f"{count} proposta(s) enviada(s) para a caixa de revisão.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
