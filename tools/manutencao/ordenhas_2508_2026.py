"""Manhã, tarde e observação das leituras de 25/08/2026.

As leituras de 25/08 entraram só com o total (a baseline, a importação e o
lançamento manual da época guardavam só isso). A planilha conferida de 25/08
tem manhã, tarde e a observação de cada vaca; com a folha completa, o sistema
passa a guardá-las, e a folha impressa de 25/08 sai igual à planilha.

Roda dentro do contêiner da API (como conciliar_agosto_2026.py), depois da
migração 0016. Sem --aplicar, só mostra o que faria.

    docker cp tools/manutencao/ordenhas_2508_2026.py <api>:/tmp/o.py
    docker cp <linhas.json> <api>:/tmp/linhas.json
    docker compose ... exec -T api uv run --no-sync python /tmp/o.py /tmp/linhas.json --autor EMAIL [--aplicar]

`linhas.json` é a associação já conferida da planilha com as fichas (uma
entrada por vaca lançada: brinco do cadastro, ou o nome quando a ficha não
tem brinco, manhã, tarde, total e observação). Fica fora do git: é dado do
rebanho.

Nada muda o total: a leitura só é completada quando manhã + tarde bate com o
total já lançado. O que não bate é listado, não gravado.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import select

from app.db.models import Animal, OfficialMeasurement, User
from app.core.legacy_maintenance import require_legacy_single_farm
from app.db.session import get_session_factory
from app.services.production_entry import (
    ProductionEntryError,
    clean_note,
    merge_reading,
    milkings_of,
    producao_of,
    reading_values,
    supersede,
)

DIA = date(2026, 8, 25)
MOTIVO = "Manhã, tarde e observação da planilha conferida de 25/08/2026 (decisão do titular em 23/09/2026)."


async def main(arquivo: Path, autor: str, aplicar: bool) -> int:
    linhas = json.loads(arquivo.read_text(encoding="utf-8"))
    async with get_session_factory()() as s:
        usuario = await s.scalar(select(User).where(User.email == autor))
        if usuario is None or usuario.role != "admin":
            raise SystemExit(f"{autor} não é administrador nesta instalação")
        fazenda = await require_legacy_single_farm(s)

        completar, iguais, problemas = [], 0, []
        for linha in linhas:
            rotulo = f"{linha.get('brinco') or 'sem brinco'} {linha['nome']}"
            filtro = (
                Animal.brinco == linha["brinco"]
                if linha.get("brinco")
                else (Animal.name == linha["nome"]) & Animal.brinco.is_(None)
            )
            animais = list(await s.scalars(select(Animal).where(filtro, Animal.merged_into_id.is_(None))))
            if len(animais) != 1:
                problemas.append(f"{rotulo}: {len(animais)} fichas")
                continue
            leitura = await s.scalar(
                select(OfficialMeasurement).where(
                    OfficialMeasurement.animal_id == animais[0].id,
                    OfficialMeasurement.measured_on == DIA,
                    OfficialMeasurement.status == "active",
                )
            )
            if leitura is None:
                problemas.append(f"{rotulo}: sem leitura em 25/08")
                continue
            try:
                valores = reading_values(
                    producao=linha["total"], manha=linha.get("manha"), tarde=linha.get("tarde")
                )
            except ProductionEntryError as erro:
                problemas.append(f"{rotulo}: {erro}")
                continue
            juntou = merge_reading(leitura, valores, clean_note(linha.get("obs")))
            if juntou is None:
                problemas.append(
                    f"{rotulo}: planilha {valores} {linha.get('obs')!r} não completa o lançado "
                    f"({producao_of(leitura)} L {milkings_of(leitura)} {leitura.observacao!r})"
                )
                continue
            novos, nota = juntou
            if novos == {"producao": producao_of(leitura), **milkings_of(leitura)} and nota == leitura.observacao:
                iguais += 1
                continue
            completar.append((rotulo, leitura, novos, nota))

        print(f"{len(linhas)} vacas na planilha: {len(completar)} a completar, {iguais} já completas, "
              f"{len(problemas)} com problema")
        for rotulo, _, novos, nota in completar[:5]:
            print(f"  ex.: {rotulo}: {novos}{f' · {nota}' if nota else ''}")
        for problema in problemas:
            print(f"  ! {problema}")

        if not aplicar:
            print("\nSIMULAÇÃO: nada foi gravado. Use --aplicar.")
            return 0
        if problemas:
            print("\nHá problemas: nada foi gravado. Resolva antes de aplicar.")
            return 1

        for _, leitura, novos, nota in completar:
            await supersede(
                s,
                farm_id=fazenda,
                user=usuario,
                previous=leitura,
                values=novos,
                observacao=nota,
                action="measurement_completed",
                reason=MOTIVO,
            )
        await s.commit()
        print(f"\n{len(completar)} leituras completadas.")
        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("linhas", type=Path)
    parser.add_argument("--autor", required=True)
    parser.add_argument("--aplicar", action="store_true")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.linhas, args.autor, args.aplicar)))
