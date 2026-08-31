from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Animal


@dataclass(frozen=True)
class AnimalMatchResult:
    animal: Animal | None
    is_ambiguous: bool
    candidate_count: int


async def find_animal_candidates(
    session: AsyncSession,
    *,
    farm_id: UUID,
    animal_number: str | None,
    animal_name: str | None,
) -> list[Animal]:
    """Matches by exact tag/number first; falls back to normalized name only
    when no number was read at all, per the plan's matching order."""
    if animal_number:
        by_tag = list(
            await session.scalars(
                select(Animal).where(
                    Animal.farm_id == farm_id, Animal.identifier == animal_number
                )
            )
        )
        if by_tag:
            return by_tag

    if animal_name:
        return list(
            await session.scalars(
                select(Animal).where(
                    Animal.farm_id == farm_id,
                    func.lower(Animal.name) == animal_name.strip().lower(),
                )
            )
        )

    return []


def resolve_animal_match(candidates: list[Animal]) -> AnimalMatchResult:
    if not candidates:
        return AnimalMatchResult(animal=None, is_ambiguous=False, candidate_count=0)
    if len(candidates) > 1:
        return AnimalMatchResult(
            animal=None, is_ambiguous=True, candidate_count=len(candidates)
        )
    return AnimalMatchResult(animal=candidates[0], is_ambiguous=False, candidate_count=1)
