"""CLI da importação da baseline legada.

Simulação é o padrão: aplicar exige ``--apply`` explícito. O relatório é o
mesmo nos dois modos, então dá para conferir exatamente o que vai acontecer
antes de autorizar a escrita.

    # simula e mostra o relatório
    uv run python -m app.core.import_baseline \
        --state ../../belo-vale-ii-projeto-completo/plataforma/state_canonical.json \
        --farm-id <uuid> --approved-by "nome@fazenda" --reference-date 2026-08-25

    # aplica
    ... --apply
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path
from uuid import UUID

from app.db.session import get_session_factory
from app.services.baseline_importer import import_baseline
from app.services.baseline_snapshot import parse_baseline


async def _run(
    *,
    state_path: Path,
    farm_id: UUID,
    approved_by: str,
    reference_date: date,
    apply: bool,
    notes: str | None,
) -> int:
    text = state_path.read_text(encoding="utf-8")
    snapshot = parse_baseline(text)

    print(f"origem: {state_path}")
    print(f"sha256: {snapshot.source_sha256}")
    print(f"animais no arquivo: {snapshot.animal_count}")
    print(f"medições no arquivo: {snapshot.measurement_count}")
    print()

    async with get_session_factory()() as session:
        report = await import_baseline(
            session,
            snapshot,
            farm_id=farm_id,
            approved_by=approved_by,
            reference_date=reference_date,
            source_path=str(state_path),
            dry_run=not apply,
            notes=notes,
        )

    for line in report.as_lines():
        print(line)

    if report.errors:
        print("\nnada foi gravado: o arquivo não passou na validação.", file=sys.stderr)
        return 1
    if not apply:
        print("\nsimulação concluída. Use --apply para gravar.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Importa a baseline legada para o PostgreSQL. Simula por padrão; "
            "grava apenas com --apply."
        )
    )
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--farm-id", type=UUID, required=True)
    parser.add_argument(
        "--approved-by",
        required=True,
        help="Responsável que autoriza a importação; fica registrado na auditoria.",
    )
    parser.add_argument(
        "--reference-date",
        type=date.fromisoformat,
        required=True,
        help=(
            "Data a partir da qual a lotação observada passa a valer. A baseline "
            "não diz desde quando cada animal está em seu lote, então esta data "
            "é declarada, não inferida."
        ),
    )
    parser.add_argument("--notes", default=None)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Grava de fato. Sem esta opção, nada é escrito.",
    )
    args = parser.parse_args(argv)

    return asyncio.run(
        _run(
            state_path=args.state,
            farm_id=args.farm_id,
            approved_by=args.approved_by,
            reference_date=args.reference_date,
            apply=args.apply,
            notes=args.notes,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
