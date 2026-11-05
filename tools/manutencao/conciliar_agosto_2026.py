"""Conciliação do cadastro antes de importar a pesagem de 25/08/2026.

Roda dentro do contêiner da API, com as mesmas funções que o app usa — cada
mudança exige evidência e vai para a auditoria com o autor:

    docker cp tools/manutencao/conciliar_agosto_2026.py <api>:/tmp/c.py
    docker compose ... exec -T api uv run --no-sync python /tmp/c.py --autor EMAIL [--aplicar]

Sem --aplicar, só mostra o que faria.

Decisões do titular (conversa de 22/09/2026):

1. Levar para a produção as correções de 19/09, feitas no banco antigo:
   - o 649 é da BRANQUINHA (folha de 25/08, 2º lote), não da REDONDA;
   - SAIA BRANCA, MEIAS BRANCA e BRANQUINHA têm ficha duplicada sem brinco
     com a produção de 22/07 — juntar na ficha com brinco.
2. Os prefixos "B1-"/"B2-" dos brincos foram erros de leitura do sistema
   antigo: o brinco é o número. Onde a planilha conferida de 25/08 escreve o
   número com outros zeros à esquerda, vale o da planilha.
   Ficam de fora, para decisão: B1-016VD (formato estranho).
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys

from sqlalchemy import select

from app.db.models import Animal, User
from app.core.legacy_maintenance import require_legacy_single_farm
from app.db.session import get_session_factory
from app.services.animal_merge import merge_animals, plan_merge
from app.services.animal_registry import link_brinco, unlink_brinco

DECISAO = "decisão do titular em 22/09/2026"

# Número como escrito na planilha conferida de 25/08/2026 (mesma vaca, mesmo
# número, só os zeros à esquerda diferem do cadastro antigo).
COMO_NA_PLANILHA = {"B2-0015": "015", "B2-0023": "023", "B2-11": "011"}

# Fora da troca automática: decisão pendente ou tratados no passo 1.
FORA = {"B1-016VD", "B2-649", "B2-549"}

PREFIXO = re.compile(r"^B[0-9]+-")


def rotulo(a: Animal) -> str:
    return f"{a.brinco or 'sem brinco'} · {a.name or 'sem nome'} (nº antigo {a.numero_legado or '—'})"


async def uma(session, **filtro) -> Animal:
    query = select(Animal)
    for campo, valor in filtro.items():
        query = query.where(getattr(Animal, campo) == valor)
    achados = list(await session.scalars(query))
    if len(achados) != 1:
        raise SystemExit(f"esperava 1 ficha para {filtro}, achei {len(achados)}")
    return achados[0]


async def main(autor: str, aplicar: bool) -> int:
    fabrica = get_session_factory()
    async with fabrica() as session:
        usuario = await session.scalar(select(User).where(User.email == autor))
        if usuario is None or usuario.role != "admin":
            raise SystemExit(f"{autor} não é administrador nesta instalação")
        # Monofazenda: a fazenda é a das fichas.
        fazenda = await require_legacy_single_farm(session)

        print("== Passo 1: correções de 19/09 ==")
        redonda = await uma(session, name="REDONDA", brinco="B2-649")
        branquinha = await uma(session, name="BRANQUINHA")
        print(f"- tirar o brinco de {rotulo(redonda)}")
        print(f"- vincular 649 a {rotulo(branquinha)}")
        juntar = []
        for certa, duplicada in (("SAIA BRANCA", "Saia Branca"), ("MEIAS BRANCA", "Meias Branca"), ("BRANQUINHA", "Branquinha")):
            a = await uma(session, name=certa)
            b = await uma(session, name=duplicada)
            juntar.append((a, b))
            plano = await plan_merge(session, farm_id=fazenda, animal_id=a.id, other_id=b.id)
            impedimentos = f" IMPEDIDO: {plano.blockers}" if plano.blockers else ""
            print(f"- juntar {rotulo(b)} em {rotulo(a)}: {len(plano.moves)} produção(ões) mudam de ficha{impedimentos}")

        print("\n== Passo 2: prefixos ==")
        prefixados = list(await session.scalars(select(Animal).where(Animal.brinco.op("~")("^B[0-9]+-")).order_by(Animal.brinco)))
        trocas = []
        for a in prefixados:
            if a.brinco in FORA:
                continue
            novo = COMO_NA_PLANILHA.get(a.brinco, PREFIXO.sub("", a.brinco))
            dono = await session.scalar(select(Animal).where(Animal.farm_id == a.farm_id, Animal.brinco == novo))
            if dono is not None:
                print(f"! {a.brinco} → {novo} colide com {rotulo(dono)}: fica de fora")
                continue
            trocas.append((a, novo))
        print(f"- {len(trocas)} brincos perdem o prefixo; fora: {sorted(FORA)}")

        if not aplicar:
            print("\nSIMULAÇÃO: nada foi gravado. Use --aplicar.")
            return 0

        print("\n== Aplicando ==")
        await unlink_brinco(
            session, animal_id=redonda.id, farm_id=fazenda, actor=autor,
            evidence="O 649 é da BRANQUINHA (folha de 25/08/2026, 2º lote), confirmado pelo titular; "
            "a REDONDA fica sem brinco até ser conferida no curral. Correção de 19/09 levada à produção.",
        )
        await link_brinco(
            session, animal_id=branquinha.id, farm_id=fazenda, actor=autor, brinco="649",
            evidence="Folha de 25/08/2026, 2º lote: 649 BRANQUINHA; confirmado pelo titular. "
            "Correção de 19/09 levada à produção.",
        )
        print("- 649: REDONDA → BRANQUINHA")
        for a, b in juntar:
            await merge_animals(
                session, farm_id=fazenda, user=usuario, animal_id=a.id, other_id=b.id,
                reason=f"Ficha duplicada (conferência de 25/08/2026): a produção de 22/07 estava na ficha "
                f"sem brinco (nº antigo {b.numero_legado}). Correção de 19/09 levada à produção; {DECISAO}.",
            )
            print(f"- juntada: {b.name} (nº antigo {b.numero_legado}) → {a.name}")
        for a, novo in trocas:
            antigo = a.brinco
            await link_brinco(
                session, animal_id=a.id, farm_id=fazenda, actor=autor, brinco=novo,
                evidence=f"Prefixo de {antigo} era erro de leitura do sistema antigo; o brinco é o número"
                + (" como escrito na planilha conferida de 25/08/2026" if antigo in COMO_NA_PLANILHA else "")
                + f" ({DECISAO}).",
            )
        print(f"- {len(trocas)} brincos sem prefixo")
        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--autor", required=True)
    parser.add_argument("--aplicar", action="store_true")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.autor, args.aplicar)))
