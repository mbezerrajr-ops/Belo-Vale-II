"""Lote de ordenha × grupo de manejo.

O campo `lote` da plataforma legada mistura dois conceitos. A distinção existia
lá (`LOTES_DIETA` e `LOTES_MANEJO` no HTML publicado) e se perdeu na migração
para o PostgreSQL, que gravou os dois no mesmo campo sem tipo.

- **Lote de ordenha** (`LOTE 1`, `LOTE 2`, `LOTE 3`): recebe dieta cadastrada,
  tem custo diário e é o agrupamento em que a vaca produz. Todos os 126
  animais nesses lotes estão em lactação, e é só para eles que existe dieta.
- **Grupo de manejo** (`BEZERREIRO`, `CAJARANAS`, `ENGORDA`, `PRÉ-PARTO`…):
  nomes de áreas e categorias da fazenda. Dizem *onde o animal está*, não como
  é arraçoado. Nenhum tem dieta cadastrada.

Dizer que uma vaca seca está "no lote BEZERREIRO" é falso: ela não está em
lote nenhum. É por isso que o tipo vive aqui, no domínio, e não numa lista
solta na tela.
"""

from __future__ import annotations

import re
import unicodedata

KIND_DIET = "diet"
KIND_MANAGEMENT = "management"

#: Lotes de ordenha. Só estes têm dieta e custo.
DIET_LOTS = frozenset({"LOTE 1", "LOTE 2", "LOTE 3"})

#: Áreas e categorias de manejo da baseline.
MANAGEMENT_GROUPS = frozenset(
    {
        "PRÉ-PARTO",
        "PIQUETES / REPASSE",
        "ENGORDA",
        "ENGENHO",
        "INSERLEITE",
        "BEZERREIRO",
        "CAJARANAS",
        "PALMA",
        "COLÉGIO",
        "ABREU",
    }
)


def _fold(value: str) -> str:
    """Sem acento, caixa alta e espaços colapsados, para comparar com robustez."""
    decomposed = unicodedata.normalize("NFKD", value)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", stripped).strip().upper()


_DIET_FOLDED = {_fold(name) for name in DIET_LOTS}
_MANAGEMENT_FOLDED = {_fold(name) for name in MANAGEMENT_GROUPS}


def classify_lot(lote: str | None) -> str | None:
    """Tipo da lotação, ou ``None`` quando não há valor.

    Um nome desconhecido é classificado como grupo de manejo. Chamá-lo de lote
    de ordenha produziria custo por vaca igual a zero — que se lê como "não
    custa nada" em vez de "ainda não há dieta cadastrada".
    """
    if lote is None:
        return None
    folded = _fold(lote)
    if not folded:
        return None
    if folded in _DIET_FOLDED:
        return KIND_DIET
    return KIND_MANAGEMENT


def is_known_lot(lote: str | None) -> bool:
    """Se o valor é um dos treze nomes que a fazenda já usa."""
    if lote is None:
        return False
    folded = _fold(lote)
    return folded in _DIET_FOLDED or folded in _MANAGEMENT_FOLDED
