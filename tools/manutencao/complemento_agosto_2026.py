"""Complemento da pesagem de 25/08/2026 e manejo anotado na folha.

Roda dentro do contêiner da API (como conciliar_agosto_2026.py), com as
funções do app. Sem --aplicar, só mostra o que faria.

Decisões do titular (22/09/2026), sobre as linhas que a importação não
associou sozinha:

- número repetido na folha → a vaca dona do brinco;
- um dígito trocado na folha → a ficha com o nome e o brinco do cadastro;
- sem número na folha → a ficha com brinco daquele nome;
- REDONDA ficou sem brinco (o 649 é da BRANQUINHA) → lançamento na ficha;
- 541 BANIA/BAIANA, 493 DUNOFINO e 732 PRAUNA ficam de fora (a identificar);
- QUARTINHA aparece duas vezes na folha: é a mesma vaca, conta uma vez;
- manejo da folha aplicado: secagem na situação, com nota nas observações;
  troca de lote a partir de 26/08 (a baseline já abre os lotes em 25/08, e a
  troca anotada na pesagem vale depois dela).
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
from collections import Counter
from datetime import date

import openpyxl
from sqlalchemy import select

from app.db.models import Animal, AnimalLotAssignment, User
from app.db.session import get_session_factory
from app.services.animal_registry import assign_lot, update_animal
from app.services.production_entry import record_reading
from app.services.production_files import parse_production_file
from app.services.production_import import build_preview, commit_import

DIA = date(2026, 8, 25)
TROCA = date(2026, 8, 26)
FOLHA = "folha/planilha conferida de 25/08/2026"

# (brinco no cadastro, nome como na folha, litros)
COMPLEMENTO = [
    ("544", "XENA", 27.0), ("016", "BELMONTE", 9.5), ("649", "BRANQUINHA", 17.0),
    ("732", "PACIÊNCIA", 14.0), ("548", "PRINCESA (518 na folha)", 37.5),
    ("433", "BRUNA (473 na folha)", 19.5), ("441", "FUMAÇA (491 na folha)", 9.0),
    ("1001", "ARIZONA (1901 na folha)", 19.0), ("117", "AZEITONA (197 na folha)", 14.0),
    ("419", "VIAJANTE (519 na folha)", 7.0), ("040", "MANHOSA (090 na folha)", 4.0),
    ("380", "BAÉ (S/N na folha)", 15.5), ("434", "FAÍSCA (S/N na folha)", 23.5),
    ("658", "CARINA (S/N na folha)", 25.5),
]
REDONDA_LITROS = 5.0

TROCAS = [("859", "LOTE 2"), ("812", "LOTE 3"), ("433", "LOTE 3"), ("652", "LOTE 3"), ("637", "LOTE 3"),
          ("963", "LOTE 3"), ("732", "LOTE 3"), ("724", "LOTE 3"), ("462", "LOTE 1")]
SECAS = ["853", "633", "547", "419", "011", "040", "701"]  # e a REDONDA, sem brinco


def planilha() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Brinco", "Nome", "Litros"])
    for brinco, nome, litros in COMPLEMENTO:
        ws.append([brinco, nome, litros])
        ws.cell(row=ws.max_row, column=1).number_format = "@"
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


async def main(autor: str, aplicar: bool) -> int:
    async with get_session_factory()() as s:
        usuario = await s.scalar(select(User).where(User.email == autor))
        if usuario is None or usuario.role != "admin":
            raise SystemExit(f"{autor} não é administrador nesta instalação")
        fazenda = await s.scalar(select(Animal.farm_id).limit(1))
        por_brinco = {a.brinco: a for a in await s.scalars(select(Animal).where(Animal.brinco.is_not(None), Animal.merged_into_id.is_(None)))}
        redonda = await s.scalar(select(Animal).where(Animal.name == "REDONDA", Animal.merged_into_id.is_(None)))

        conteudo = planilha()
        nome_arquivo = "complemento-pesagem-2508.xlsx"
        parsed = parse_production_file(conteudo, nome_arquivo)
        previa = await build_preview(s, farm_id=fazenda, parsed=parsed, content=conteudo, filename=nome_arquivo, measured_on=DIA)
        print("complemento:", dict(Counter(r.status for r in previa.rows)))
        for r in previa.rows:
            if r.status not in ("new", "same"):
                print(f"  ! {r.brinco_lido} {r.nome_arquivo}: {r.status} {r.notes}")
        print(f"REDONDA ({'sem brinco' if redonda and not redonda.brinco else '?'}): {REDONDA_LITROS} L")

        lotes_atuais = {
            l.animal_id: l.lote for l in await s.scalars(
                select(AnimalLotAssignment).where(AnimalLotAssignment.valid_to.is_(None), AnimalLotAssignment.kind == "diet"))
        }
        for brinco, lote in TROCAS:
            a = por_brinco[brinco]
            print(f"troca: {brinco} {a.name}: {lotes_atuais.get(a.id, '—')} → {lote} a partir de {TROCA:%d/%m}")
        for brinco in SECAS:
            a = por_brinco[brinco]
            print(f"seca: {brinco} {a.name} ({a.situacao})")
        print(f"seca: sem brinco REDONDA ({redonda.situacao})")

        if not aplicar:
            print("\nSIMULAÇÃO: nada foi gravado. Use --aplicar.")
            return 0

        await commit_import(
            s, farm_id=fazenda, user=usuario, parsed=parsed, content=conteudo, filename=nome_arquivo,
            measured_on=DIA, mode="replace",
            reason="Complemento da pesagem de 25/08/2026: linhas com número repetido, dígito trocado ou sem "
            "número na folha, associadas à ficha pelo nome e conferidas pelo titular em 22/09/2026.",
        )
        await s.commit()
        await record_reading(s, farm_id=fazenda, user=usuario, animal_id=redonda.id, measured_on=DIA, producao=REDONDA_LITROS)
        await s.commit()
        print("produção: complemento importado e REDONDA lançada")

        for brinco, lote in TROCAS:
            feita = await assign_lot(s, animal_id=por_brinco[brinco].id, farm_id=fazenda, actor=autor, lote=lote, valid_from=TROCA, kind="diet")
            await s.commit()
            print(f"troca {brinco}: {'feita' if feita else 'já estava no lote'}")
        for animal in [por_brinco[b] for b in SECAS] + [redonda]:
            nota = f"Seca pela {FOLHA} (aplicado em 22/09/2026, decisão do titular)."
            obs = f"{animal.observacoes}\n{nota}" if animal.observacoes else nota
            await update_animal(s, animal_id=animal.id, farm_id=fazenda, actor=autor, changes={"situacao": "Seca", "observacoes": obs})
        print(f"secas: {len(SECAS) + 1} fichas")
        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--autor", required=True)
    parser.add_argument("--aplicar", action="store_true")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.autor, args.aplicar)))
