"""Forma canônica do brinco.

O brinco é a única chave de identidade operacional do rebanho: é por ele que
uma linha de um arquivo novo é associada a um animal existente. Por isso a
normalização é deliberadamente conservadora — padroniza espaçamento e caixa,
e nada mais.

Não completa dígitos, não corrige formato e não adivinha: `026` e `26` são
brincos diferentes e continuam diferentes. Um valor que não identifica nada
(placeholder de leitura ilegível) vira `None`, porque um animal sem brinco
legível não pode receber matching automático — mas continua sendo um animal
válido, com cadastro e histórico preservados.
"""

from __future__ import annotations

import re


_WHITESPACE = re.compile(r"\s+")

#: Marcadores de leitura ilegível encontrados na baseline e em fichas de campo.
#: Não são brincos: identificam a *ausência* de um brinco legível.
_UNREADABLE_MARKERS = frozenset({"XXX", "???", "---", "B2-XXX", "B1-XXX"})


def normalize_brinco(raw: str | None) -> str | None:
    """Devolve a forma canônica do brinco, ou ``None`` quando não há brinco.

    ``None`` significa "este animal não tem brinco legível" — um estado
    válido para 141 registros da baseline — e nunca deve ser confundido com
    um erro.
    """
    if raw is None:
        return None

    collapsed = _WHITESPACE.sub("", raw).upper()
    if not collapsed:
        return None
    if collapsed in _UNREADABLE_MARKERS:
        return None
    return collapsed
