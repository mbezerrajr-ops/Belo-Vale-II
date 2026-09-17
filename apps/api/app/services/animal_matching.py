"""Correspondência entre uma linha lida e um animal cadastrado.

O brinco é a **única** chave de correspondência automática. Nome não
identifica animal: a base tem nomes repetidos, e o mesmo nome em brincos
diferentes significa animais diferentes — casar por nome fundiria históricos
de animais distintos.

Não há fallback. Uma linha sem brinco legível simplesmente não é associada a
ninguém automaticamente; ela vai para decisão humana, que é onde o nome lido
volta a ser útil como evidência para uma pessoa — nunca para a máquina.

O resultado carrega o brinco lido, o normalizado, o método usado e o motivo de
não ter casado, para que a revisão e a auditoria saibam exatamente como cada
linha chegou onde chegou.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Animal
from app.services.brinco import normalize_brinco


#: Método de correspondência registrado no resultado.
MATCH_BY_BRINCO = "brinco"
MATCH_NONE = "none"

_REASON_NO_BRINCO = "Linha sem brinco: não há chave de correspondência automática."
_REASON_UNREADABLE = (
    "Brinco ilegível: o valor lido não identifica um animal."
)
_REASON_NOT_FOUND = "Nenhum animal cadastrado tem este brinco."
_REASON_AMBIGUOUS = "Mais de um animal cadastrado tem este brinco."


@dataclass(frozen=True)
class AnimalMatchResult:
    animal: Animal | None
    is_ambiguous: bool
    candidate_count: int
    method: str
    brinco_lido: str | None
    brinco_normalizado: str | None
    reason: str | None

    @property
    def matched(self) -> bool:
        return self.animal is not None


async def find_animal_candidates(
    session: AsyncSession,
    *,
    farm_id: UUID,
    brinco: str | None,
) -> list[Animal]:
    """Busca por brinco normalizado. Sem brinco legível, não há candidatos.

    Animais sem brinco nunca são devolvidos: `Animal.brinco IS NULL` jamais
    casa com um valor lido.
    """
    normalized = normalize_brinco(brinco)
    if normalized is None:
        return []

    return list(
        await session.scalars(
            select(Animal).where(
                Animal.farm_id == farm_id, Animal.brinco == normalized
            )
        )
    )


def resolve_animal_match(
    candidates: list[Animal],
    *,
    brinco_lido: str | None,
    brinco_normalizado: str | None,
) -> AnimalMatchResult:
    def result(
        *, animal: Animal | None, ambiguous: bool, method: str, reason: str | None
    ) -> AnimalMatchResult:
        return AnimalMatchResult(
            animal=animal,
            is_ambiguous=ambiguous,
            candidate_count=len(candidates),
            method=method,
            brinco_lido=brinco_lido,
            brinco_normalizado=brinco_normalizado,
            reason=reason,
        )

    if len(candidates) > 1:
        return result(
            animal=None, ambiguous=True, method=MATCH_NONE, reason=_REASON_AMBIGUOUS
        )
    if len(candidates) == 1:
        return result(
            animal=candidates[0],
            ambiguous=False,
            method=MATCH_BY_BRINCO,
            reason=None,
        )

    if brinco_normalizado is not None:
        reason = _REASON_NOT_FOUND
    elif brinco_lido and brinco_lido.strip():
        reason = _REASON_UNREADABLE
    else:
        reason = _REASON_NO_BRINCO
    return result(animal=None, ambiguous=False, method=MATCH_NONE, reason=reason)


async def match_animal(
    session: AsyncSession, *, farm_id: UUID, brinco: str | None
) -> AnimalMatchResult:
    """Conveniência: busca e resolve numa chamada, preservando o valor lido."""
    normalized = normalize_brinco(brinco)
    candidates = await find_animal_candidates(session, farm_id=farm_id, brinco=brinco)
    return resolve_animal_match(
        candidates, brinco_lido=brinco, brinco_normalizado=normalized
    )
