"""Endpoints do cadastro mestre: fazenda e animais.

A fazenda é resolvida no servidor. Nenhum endpoint aceita `farm_id` do
cliente: numa operação monofazenda, deixar o cliente escolher a fazenda seria
autorização de domínio delegada ao navegador.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_minimum_role
from app.db.models import Animal, Farm, User
from app.db.session import get_db_session
from app.schemas.registry import (
    AnimalCreate,
    AnimalDetail,
    AnimalPage,
    AnimalRead,
    AnimalUpdate,
    BrincoLink,
    FarmCreate,
    FarmRead,
    LotAssign,
    LotAssignmentRead,
)
from app.services.animal_registry import (
    AnimalRegistryError,
    assign_lot,
    create_animal,
    current_lot,
    link_brinco,
    lot_history,
    update_animal,
)
from app.services.brinco import normalize_brinco
from app.services.lot_kind import KIND_DIET, KIND_MANAGEMENT

router = APIRouter(prefix="/api", tags=["registry"])


async def resolve_current_farm(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Farm:
    """A fazenda da operação, resolvida no servidor.

    Enquanto a operação for monofazenda, existe exatamente uma. Mais de uma é
    um estado que este modo não sabe desambiguar sozinho — falhar aqui é mais
    seguro do que escolher uma.
    """
    farms = list(await session.scalars(select(Farm).order_by(Farm.created_at)))
    if not farms:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Nenhuma fazenda cadastrada. Crie a primeira em POST /api/farms."
            ),
        )
    if len(farms) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Mais de uma fazenda cadastrada, mas a operação está configurada "
                "como monofazenda. Defina o modelo de autorização por fazenda "
                "antes de seguir."
            ),
        )
    return farms[0]


def _conflict(error: AnimalRegistryError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))


async def _read_model(session: AsyncSession, animal: Animal) -> AnimalRead:
    # Lote de ordenha e grupo de manejo vêm separados: dizer que uma vaca seca
    # está "no lote BEZERREIRO" seria falso — ela não está em lote nenhum.
    lot = await current_lot(session, animal_id=animal.id, kind=KIND_DIET)
    group = await current_lot(session, animal_id=animal.id, kind=KIND_MANAGEMENT)
    data = AnimalRead.model_validate(animal).model_dump()
    data["lote_atual"] = lot.lote if lot else None
    data["grupo_manejo"] = group.lote if group else None
    return AnimalRead(**data)


@router.post("/farms", response_model=FarmRead, status_code=status.HTTP_201_CREATED)
async def create_farm(
    payload: FarmCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[User, Depends(require_minimum_role("admin"))],
) -> Farm:
    farm = Farm(name=payload.name, code=payload.code)
    session.add(farm)
    await session.commit()
    return farm


@router.get("/farms/current", response_model=FarmRead)
async def read_current_farm(
    farm: Annotated[Farm, Depends(resolve_current_farm)],
    _: Annotated[User, Depends(require_minimum_role("operator"))],
) -> Farm:
    return farm


@router.post("/animals", response_model=AnimalRead, status_code=status.HTTP_201_CREATED)
async def create_animal_endpoint(
    payload: AnimalCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    farm: Annotated[Farm, Depends(resolve_current_farm)],
    user: Annotated[User, Depends(require_minimum_role("reviewer"))],
) -> AnimalRead:
    try:
        animal = await create_animal(
            session,
            farm_id=farm.id,
            actor=user.email,
            brinco=payload.brinco,
            name=payload.name,
            numero_legado=payload.numero_legado,
            situacao=payload.situacao,
            status=payload.status,
            ultimo_parto=payload.ultimo_parto,
            nascimento=payload.nascimento,
            peso=payload.peso,
            observacoes=payload.observacoes,
            lote=payload.lote,
            lote_valid_from=payload.lote_valid_from,
        )
    except AnimalRegistryError as error:
        raise _conflict(error) from error
    return await _read_model(session, animal)


@router.get("/animals", response_model=AnimalPage)
async def list_animals(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    farm: Annotated[Farm, Depends(resolve_current_farm)],
    _: Annotated[User, Depends(require_minimum_role("operator"))],
    brinco: str | None = Query(default=None),
    name: str | None = Query(default=None),
    sem_brinco: bool = Query(
        default=False, description="Apenas animais sem brinco legível."
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> AnimalPage:
    filters = [Animal.farm_id == farm.id]
    if brinco:
        normalized = normalize_brinco(brinco)
        # Um termo ilegível não pode virar "qualquer coisa": não casa nada.
        filters.append(Animal.brinco == normalized if normalized else Animal.id.is_(None))
    if name:
        filters.append(func.lower(Animal.name).contains(name.strip().lower()))
    if sem_brinco:
        filters.append(Animal.brinco.is_(None))

    total = await session.scalar(
        select(func.count()).select_from(Animal).where(*filters)
    )
    animals = list(
        await session.scalars(
            select(Animal)
            .where(*filters)
            .order_by(Animal.name, Animal.created_at)
            .limit(limit)
            .offset(offset)
        )
    )
    return AnimalPage(
        items=[await _read_model(session, animal) for animal in animals],
        total=total or 0,
        limit=limit,
        offset=offset,
    )


async def _load_or_404(session: AsyncSession, animal_id: UUID, farm_id: UUID) -> Animal:
    animal = await session.scalar(
        select(Animal).where(Animal.id == animal_id, Animal.farm_id == farm_id)
    )
    if animal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Animal não encontrado."
        )
    return animal


@router.get("/animals/{animal_id}", response_model=AnimalDetail)
async def read_animal(
    animal_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    farm: Annotated[Farm, Depends(resolve_current_farm)],
    _: Annotated[User, Depends(require_minimum_role("operator"))],
) -> AnimalDetail:
    animal = await _load_or_404(session, animal_id, farm.id)
    history = await lot_history(session, animal_id=animal.id)
    base = await _read_model(session, animal)
    return AnimalDetail(
        **base.model_dump(),
        historico_lotes=[LotAssignmentRead.model_validate(row) for row in history],
    )


@router.patch("/animals/{animal_id}", response_model=AnimalRead)
async def patch_animal(
    animal_id: UUID,
    payload: AnimalUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    farm: Annotated[Farm, Depends(resolve_current_farm)],
    user: Annotated[User, Depends(require_minimum_role("reviewer"))],
) -> AnimalRead:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Nada a alterar."
        )
    try:
        animal = await update_animal(
            session,
            animal_id=animal_id,
            farm_id=farm.id,
            actor=user.email,
            changes=changes,
        )
    except AnimalRegistryError as error:
        raise _conflict(error) from error
    return await _read_model(session, animal)


@router.post("/animals/{animal_id}/brinco", response_model=AnimalRead)
async def link_brinco_endpoint(
    animal_id: UUID,
    payload: BrincoLink,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    farm: Annotated[Farm, Depends(resolve_current_farm)],
    user: Annotated[User, Depends(require_minimum_role("reviewer"))],
) -> AnimalRead:
    if not payload.evidence.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Vincular um brinco muda a identidade operacional do animal: "
                "informe a evidência que sustenta a decisão."
            ),
        )
    try:
        animal = await link_brinco(
            session,
            animal_id=animal_id,
            farm_id=farm.id,
            actor=user.email,
            brinco=payload.brinco,
            evidence=payload.evidence,
        )
    except AnimalRegistryError as error:
        raise _conflict(error) from error
    return await _read_model(session, animal)


@router.post("/animals/{animal_id}/lote", response_model=AnimalRead)
async def assign_lot_endpoint(
    animal_id: UUID,
    payload: LotAssign,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    farm: Annotated[Farm, Depends(resolve_current_farm)],
    user: Annotated[User, Depends(require_minimum_role("reviewer"))],
) -> AnimalRead:
    try:
        await assign_lot(
            session,
            animal_id=animal_id,
            farm_id=farm.id,
            actor=user.email,
            lote=payload.lote,
            valid_from=payload.valid_from,
            kind=payload.kind,
        )
    except AnimalRegistryError as error:
        raise _conflict(error) from error
    animal = await _load_or_404(session, animal_id, farm.id)
    return await _read_model(session, animal)
