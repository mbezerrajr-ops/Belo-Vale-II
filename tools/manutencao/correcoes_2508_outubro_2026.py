"""Correções da pesagem de 25/08/2026, decididas pelo titular em 06/10/2026.

Roda dentro do contêiner da API (como conciliar_agosto_2026.py), com as
funções do app — cada mudança vai para a auditoria com o autor. Sem
--aplicar, só mostra o que faria:

    docker cp tools/manutencao/correcoes_2508_outubro_2026.py belo-vale-api-1:/tmp/c.py
    docker exec -e PYTHONPATH=/app belo-vale-api-1 uv run --no-sync python /tmp/c.py --autor EMAIL [--aplicar]
    docker exec -u 0 belo-vale-api-1 rm -f /tmp/c.py

(`PYTHONPATH=/app`: rodando de /tmp, o Python não acha o pacote `app`.)

Revendo, linha a linha, a planilha conferida de 25/08 contra o que foi
aplicado em 22/09, o titular corrigiu três decisões daquela data:

1. "541 BANIA/BAIANA" é a BAHIA, brinco 591 — não a BAIANA. A leitura de
   25/08 sai da BAIANA (anulada, com motivo) e vai para a BAHIA com os mesmos
   valores; o 541, que a BAIANA ganhou só por essa linha, sai da ficha dela.
2. O brinco da PRINCESA é 518, como está na folha (em 22/09 ficou o 548 do
   cadastro, tratando o 518 como dígito trocado).
3. Nomes: o 1013 é a CODORNA (o cadastro dizia Boemia) e o 733 é a PRAUNA (o
   cadastro dizia Pauna).

Fica de fora, para confirmar com o cliente: BORBOLETA e BELMONTE aparecem
com o mesmo brinco (016) na folha (ver docs/known-issues.md).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date

from sqlalchemy import select

from app.db.models import Animal, AnimalLotAssignment, OfficialMeasurement, User
from app.core.legacy_maintenance import require_legacy_single_farm
from app.db.session import get_session_factory
from app.services.animal_registry import link_brinco, unlink_brinco, update_animal
from app.services.production_entry import diet_lot_on, milkings_of, producao_of, record_reading, void_reading

DIA = date(2026, 8, 25)
DECISAO = "decisão do titular em 06/10/2026"

# (brinco, nome no cadastro hoje, nome correto)
NOMES = [("1013", "BOEMIA", "CODORNA"), ("733", "PAUNA", "PRAUNA")]


async def ficha_do_brinco(s, numero: str) -> Animal:
    achados = list(await s.scalars(select(Animal).where(Animal.merged_into_id.is_(None), Animal.brinco == numero)))
    if len(achados) != 1:
        raise SystemExit(
            f"esperava 1 ficha com o brinco {numero}, achei {len(achados)}"
            + (" — as correções já foram aplicadas?" if not achados else ""))
    return achados[0]


async def leitura(s, animal_id) -> OfficialMeasurement | None:
    return await s.scalar(select(OfficialMeasurement).where(
        OfficialMeasurement.animal_id == animal_id, OfficialMeasurement.measured_on == DIA,
        OfficialMeasurement.status == "active"))


async def lotes_vigentes(s, animal_id) -> dict[str, str]:
    return {
        l.kind: l.lote for l in await s.scalars(
            select(AnimalLotAssignment).where(AnimalLotAssignment.animal_id == animal_id, AnimalLotAssignment.valid_to.is_(None)))
    }


def descreve(m: OfficialMeasurement) -> str:
    partes = milkings_of(m)
    ordenhas = f" ({partes.get('manha', '—')} + {partes.get('tarde', '—')})" if partes else ""
    return f"{producao_of(m)} L{ordenhas}" + (f", obs. \"{m.observacao}\"" if m.observacao else "")


def anota(animal: Animal, nota: str) -> str:
    return f"{animal.observacoes}\n{nota}" if animal.observacoes else nota


async def main(autor: str, aplicar: bool) -> int:
    async with get_session_factory()() as s:
        usuario = await s.scalar(select(User).where(User.email == autor))
        if usuario is None or usuario.role != "admin":
            raise SystemExit(f"{autor} não é administrador nesta instalação")
        fazenda = await require_legacy_single_farm(s)

        print("== 1. A linha '541 BANIA/BAIANA' é a BAHIA 591 ==")
        baiana = await ficha_do_brinco(s, "541")
        if baiana.name.strip().upper() != "BAIANA":
            raise SystemExit(f"o 541 é de {baiana.name}, não da BAIANA: o cadastro mudou desde 22/09")
        bahia = await ficha_do_brinco(s, "591")
        da_baiana = await leitura(s, baiana.id)
        if da_baiana is None:
            raise SystemExit("a BAIANA não tem leitura ativa em 25/08: nada a mover")
        da_bahia = await leitura(s, bahia.id)
        if da_bahia is not None:
            raise SystemExit(f"a 591 {bahia.name} já tem leitura em 25/08 ({descreve(da_bahia)}): decidir à mão")
        print(f"- leitura de 25/08: {descreve(da_baiana)}")
        print(f"  sai da BAIANA (541, lotes {await lotes_vigentes(s, baiana.id) or '—'})")
        print(f"  vai para a 591 {bahia.name} ({bahia.situacao}, lotes {await lotes_vigentes(s, bahia.id) or '—'})")
        lote_em_2508 = await diet_lot_on(s, animal_id=bahia.id, day=DIA)
        if lote_em_2508 != "LOTE 1":
            # A leitura fica no lote em que a vaca estava no dia; mudar o lote
            # é decisão à parte, que este script não toma.
            print(f"  ATENÇÃO: a folha põe esta linha no 1º lote, mas em 25/08 a {bahia.name} estava em "
                  f"{lote_em_2508 or 'nenhum lote de ordenha'}; a leitura entra nesse lote.")
        print("- o 541 sai da ficha da BAIANA, que volta a ficar sem brinco")

        print("\n== 2. PRINCESA: brinco 518 ==")
        princesa = await ficha_do_brinco(s, "548")
        if princesa.name.strip().upper() != "PRINCESA":
            raise SystemExit(f"o 548 é de {princesa.name}, não da PRINCESA")
        dono_518 = await s.scalar(select(Animal).where(Animal.brinco == "518"))
        if dono_518 is not None:
            raise SystemExit(f"o 518 já é de {dono_518.name}")
        da_princesa = await leitura(s, princesa.id)
        print(f"- 548 → 518 na ficha da PRINCESA (leitura de 25/08: {descreve(da_princesa) if da_princesa else '—'})")

        print("\n== 3. Nomes ==")
        renomear = []
        for numero, atual, correto in NOMES:
            a = await ficha_do_brinco(s, numero)
            if a.name.strip().upper() == correto:
                print(f"- {numero}: já é {correto}")
                continue
            if a.name.strip().upper() != atual:
                raise SystemExit(f"o {numero} se chama {a.name}, esperava {atual}")
            print(f"- {numero}: {a.name} → {correto}")
            renomear.append((a, correto))

        if not aplicar:
            print("\nSIMULAÇÃO: nada foi gravado. Use --aplicar.")
            return 0

        print("\n== Aplicando ==")
        motivo = (f"Pesagem de 25/08/2026, 1º lote, '541 BANIA/BAIANA': a vaca é a BAHIA, brinco 591, "
                  f"não a BAIANA ({DECISAO}; revê a decisão de 22/09).")
        partes = milkings_of(da_baiana)
        await void_reading(s, farm_id=fazenda, user=usuario, measurement_id=da_baiana.id, reason=motivo)
        if "manha" in partes and "tarde" in partes:
            await record_reading(s, farm_id=fazenda, user=usuario, animal_id=bahia.id, measured_on=DIA,
                                 manha=partes["manha"], tarde=partes["tarde"], observacao=da_baiana.observacao)
        else:
            await record_reading(s, farm_id=fazenda, user=usuario, animal_id=bahia.id, measured_on=DIA,
                                 producao=producao_of(da_baiana), observacao=da_baiana.observacao)
        await s.commit()
        print(f"- leitura de 25/08 movida da BAIANA para a 591 {bahia.name}")

        await unlink_brinco(s, animal_id=baiana.id, farm_id=fazenda, actor=autor, evidence=(
            f"O 541 veio só da linha '541 BANIA/BAIANA' da folha de 25/08, que é da BAHIA 591 ({DECISAO})."))
        await update_animal(s, animal_id=baiana.id, farm_id=fazenda, actor=autor, changes={"observacoes": anota(
            baiana, f"Sem brinco: o 541 tinha vindo da linha '541 BANIA/BAIANA' de 25/08, que é da BAHIA 591 ({DECISAO}).")})
        print("- BAIANA sem brinco")

        await link_brinco(s, animal_id=princesa.id, farm_id=fazenda, actor=autor, brinco="518", evidence=(
            f"Folha de 25/08/2026, 1º lote: '518 PRINCESA'; o brinco dela é o 518 ({DECISAO}; "
            "em 22/09 tinha ficado o 548 do cadastro)."))
        print("- PRINCESA: 518")

        for a, correto in renomear:
            antigo = a.name
            await update_animal(s, animal_id=a.id, farm_id=fazenda, actor=autor, changes={
                "name": correto,
                "observacoes": anota(a, f"Nome corrigido de {antigo} para {correto} ({DECISAO})."),
            })
            print(f"- {a.brinco}: {antigo} → {correto}")
        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--autor", required=True)
    parser.add_argument("--aplicar", action="store_true")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.autor, args.aplicar)))
