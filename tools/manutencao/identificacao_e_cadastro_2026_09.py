"""Vacas a identificar da pesagem de 25/08/2026 e limpeza do cadastro.

Roda dentro do contêiner da API (como conciliar_agosto_2026.py), com as
funções do app. Sem --aplicar, só mostra o que faria.

Decisões do titular (22/09/2026):

1. As três linhas da folha de 25/08 que ficaram "a identificar":
   - 732 PRAUNA é a 733 Pauna (erro de digitação na planilha);
   - 541 BANIA/BAIANA é a BAIANA, ficha sem brinco (nº antigo 390), e o 541
     passa a ser o brinco dela;
   - 493 DUNOFINO é a OURO FINO de brinco 498, outra vaca além da 598 OURO
     FINO (duas vacas com o mesmo nome); ela ainda não tinha ficha.
2. Fichas duplicadas: só as que têm o mesmo último parto na ficha sem brinco
   e na ficha com brinco — CIGANA/821 e SURUBIM/846. As demais parecidas só no
   nome vão para a conferência no curral.
3. MULATA deu 25 L no 1º lote em 25/08: volta a "Em lactação", no LOTE 1.
4. Vacas "Em lactação" que estão em PRÉ-PARTO, PIQUETES / REPASSE ou ENGORDA,
   sem lote de ordenha e fora da pesagem de 25/08, passam a "Seca".
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
from datetime import date

import openpyxl
from sqlalchemy import select

from app.db.models import Animal, AnimalLotAssignment, OfficialMeasurement, User
from app.db.session import get_session_factory
from app.services.animal_merge import merge_animals, plan_merge
from app.services.animal_registry import assign_lot, create_animal, link_brinco, update_animal
from app.services.production_files import parse_production_file
from app.services.production_import import build_preview, commit_import

DIA = date(2026, 8, 25)
DECISAO = "decisão do titular em 22/09/2026"

# (brinco no cadastro, nome como na folha, litros)
IDENTIFICADAS = [
    ("541", "BAIANA (541 BANIA/BAIANA na folha)", 28.0),
    ("733", "PAUNA (732 PRAUNA na folha)", 20.0),
    ("498", "OURO FINO (493 DUNOFINO na folha)", 15.0),
]

# (nome da ficha sem brinco, nº antigo, brinco da ficha que fica)
DUPLICADAS = [("CIGANA", "157", "821"), ("SURUBIM", "474", "846")]

GRUPOS_SEM_ORDENHA = {"PRÉ-PARTO", "PIQUETES / REPASSE", "ENGORDA"}
SECAS = [
    "598", "854", "523", "497", "879", "001", "567", "671", "573", "657",  # pesadas em 22/07, não em 25/08
    "1008", "226", "442", "511", "577", "516", "654", "678",  # nunca pesadas
]


def planilha() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Brinco", "Nome", "Litros"])
    for brinco, nome, litros in IDENTIFICADAS:
        ws.append([brinco, nome, litros])
        ws.cell(row=ws.max_row, column=1).number_format = "@"
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


async def uma(s, *condicoes) -> Animal:
    achados = list(await s.scalars(select(Animal).where(Animal.merged_into_id.is_(None), *condicoes)))
    if len(achados) != 1:
        raise SystemExit(f"esperava 1 ficha para {condicoes}, achei {len(achados)}")
    return achados[0]


async def lotes_vigentes(s, animal_id) -> dict[str, str]:
    return {
        l.kind: l.lote for l in await s.scalars(
            select(AnimalLotAssignment).where(AnimalLotAssignment.animal_id == animal_id, AnimalLotAssignment.valid_to.is_(None)))
    }


async def leitura(s, animal_id) -> float | None:
    m = await s.scalar(select(OfficialMeasurement).where(
        OfficialMeasurement.animal_id == animal_id, OfficialMeasurement.measured_on == DIA, OfficialMeasurement.status == "active"))
    return None if m is None else float(m.values["producao"])


def anota(animal: Animal, nota: str) -> str:
    return f"{animal.observacoes}\n{nota}" if animal.observacoes else nota


async def main(autor: str, aplicar: bool) -> int:
    async with get_session_factory()() as s:
        usuario = await s.scalar(select(User).where(User.email == autor))
        if usuario is None or usuario.role != "admin":
            raise SystemExit(f"{autor} não é administrador nesta instalação")
        fazenda = await s.scalar(select(Animal.farm_id).limit(1))

        print("== 1. Vacas a identificar de 25/08 ==")
        baiana = await uma(s, Animal.name == "BAIANA", Animal.numero_legado == "390")
        pauna = await uma(s, Animal.brinco == "733")
        ouro_fino_498 = await s.scalar(select(Animal).where(Animal.brinco == "498"))
        print(f"- 541 → BAIANA (hoje {baiana.brinco or 'sem brinco'}, nº antigo 390), 28 L")
        print(f"- 733 {pauna.name}: 20 L (leitura atual em 25/08: {await leitura(s, pauna.id)})")
        print(f"- 498 OURO FINO: {'ficha já existe' if ouro_fino_498 else 'ficha nova'}, 15 L")

        print("\n== 2. Fichas duplicadas ==")
        juntar = []
        for nome, legado, brinco in DUPLICADAS:
            sem = await uma(s, Animal.name == nome, Animal.numero_legado == legado, Animal.brinco.is_(None))
            com = await uma(s, Animal.brinco == brinco)
            if sem.ultimo_parto != com.ultimo_parto:
                raise SystemExit(f"{nome}: o último parto não é mais o mesmo nas duas fichas")
            plano = await plan_merge(s, farm_id=fazenda, animal_id=com.id, other_id=sem.id)
            impedimentos = f" IMPEDIDO: {plano.blockers}" if plano.blockers else ""
            print(f"- {nome} (nº antigo {legado}) → {brinco} {com.name}: parto {com.ultimo_parto:%d/%m/%Y} nas duas{impedimentos}")
            juntar.append((com, sem))

        print("\n== 3. MULATA ==")
        mulata = await uma(s, Animal.name == "MULATA", Animal.brinco.is_(None))
        print(f"- {mulata.situacao} → Em lactação; lote de ordenha {await lotes_vigentes(s, mulata.id) or '—'} → LOTE 1 desde 25/08")

        print("\n== 4. Secas ==")
        secas = []
        for brinco in SECAS:
            a = await uma(s, Animal.brinco == brinco)
            lotes = await lotes_vigentes(s, a.id)
            motivo = []
            if a.situacao != "Em lactação":
                motivo.append(f"situação é {a.situacao}")
            if "diet" in lotes:
                motivo.append(f"está no {lotes['diet']}")
            if lotes.get("management") not in GRUPOS_SEM_ORDENHA:
                motivo.append(f"grupo é {lotes.get('management')}")
            if await leitura(s, a.id) is not None:
                motivo.append("tem leitura em 25/08")
            if motivo:
                raise SystemExit(f"{brinco} {a.name}: não se encaixa mais ({'; '.join(motivo)})")
            secas.append((a, lotes["management"]))
            print(f"- {brinco} {a.name} ({lotes['management']})")

        if not aplicar:
            print("\nSIMULAÇÃO: nada foi gravado. Use --aplicar.")
            return 0

        print("\n== Aplicando ==")
        await link_brinco(
            s, animal_id=baiana.id, farm_id=fazenda, actor=autor, brinco="541",
            evidence=f"Folha de 25/08/2026, 1º lote: '541 BANIA/BAIANA'; identidade e brinco confirmados ({DECISAO}).",
        )
        if ouro_fino_498 is None:
            await create_animal(
                s, farm_id=fazenda, actor=autor, brinco="498", name="OURO FINO", situacao="Em lactação", status="Ativo",
                observacoes="Ficha criada pela folha de 25/08/2026 (2º lote, '493 DUNOFINO'): o titular identificou a vaca "
                "como Ouro Fino, brinco 498, outra vaca além da 598 OURO FINO (duas vacas com o mesmo nome). "
                "Conferir no curral.",
            )
        print("- brinco 541 na BAIANA; ficha 498 OURO FINO")

        conteudo = planilha()
        nome_arquivo = "identificadas-pesagem-2508.xlsx"
        parsed = parse_production_file(conteudo, nome_arquivo)
        previa = await build_preview(s, farm_id=fazenda, parsed=parsed, content=conteudo, filename=nome_arquivo, measured_on=DIA)
        errados = [(r.brinco_lido, r.status) for r in previa.rows if r.status != "new"]
        if errados:
            raise SystemExit(f"a importação não associou como esperado: {errados}")
        await commit_import(
            s, farm_id=fazenda, user=usuario, parsed=parsed, content=conteudo, filename=nome_arquivo,
            measured_on=DIA, mode="replace",
            reason="Pesagem de 25/08/2026: as três vacas que ficaram a identificar, identificadas pelo titular em "
            "22/09/2026 (732 PRAUNA é a 733 Pauna; 541 BANIA/BAIANA é a BAIANA; 493 DUNOFINO é a 498 OURO FINO).",
        )
        await s.commit()
        print("- produção: 3 leituras lançadas em 25/08")

        for com, sem in juntar:
            await merge_animals(
                s, farm_id=fazenda, user=usuario, animal_id=com.id, other_id=sem.id,
                reason=f"Ficha duplicada: mesmo nome e mesmo último parto ({com.ultimo_parto:%d/%m/%Y}); a ficha sem "
                f"brinco (nº antigo {sem.numero_legado}) nunca teve pesagem ({DECISAO}).",
            )
            print(f"- juntada: {sem.name} (nº antigo {sem.numero_legado}) → {com.brinco} {com.name}")

        await update_animal(
            s, animal_id=mulata.id, farm_id=fazenda, actor=autor,
            changes={"situacao": "Em lactação", "observacoes": anota(
                mulata, f"Em lactação: deu 25 L no 1º lote na pesagem de 25/08/2026 ({DECISAO}).")},
        )
        await assign_lot(s, animal_id=mulata.id, farm_id=fazenda, actor=autor, lote="LOTE 1", valid_from=DIA, kind="diet")
        print("- MULATA: Em lactação, LOTE 1 desde 25/08")

        for a, grupo in secas:
            await update_animal(
                s, animal_id=a.id, farm_id=fazenda, actor=autor,
                changes={"situacao": "Seca", "observacoes": anota(
                    a, f"Seca: estava em {grupo}, sem lote de ordenha e fora da pesagem de 25/08/2026 ({DECISAO}).")},
            )
        print(f"- secas: {len(secas)} fichas")
        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--autor", required=True)
    parser.add_argument("--aplicar", action="store_true")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.autor, args.aplicar)))
