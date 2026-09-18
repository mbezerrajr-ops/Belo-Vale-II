"""Painel do rebanho e gestão de insumos.

O painel é leitura para qualquer usuário autenticado. Mexer em preço e dieta
exige `reviewer`, porque muda o cálculo de custo de toda a fazenda.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_minimum_role
from app.db.models import AuditEvent, Farm, Supply, SupplyDiet, SupplyPrice, User
from app.db.session import get_db_session
from app.routers.registry import resolve_current_farm
from app.schemas.dashboard import (
    DashboardRead,
    DietUpdate,
    MilkPriceUpdate,
    SupplyCreate,
    SupplyRead,
    SupplyUpdate,
)
from app.services.dashboard import build_dashboard

router = APIRouter(prefix="/api", tags=["dashboard"])


async def _supply_or_404(
    session: AsyncSession, supply_id: UUID, farm_id: UUID
) -> Supply:
    supply = await session.scalar(
        select(Supply).where(Supply.id == supply_id, Supply.farm_id == farm_id)
    )
    if supply is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Insumo não encontrado."
        )
    return supply


async def _read_supply(session: AsyncSession, supply: Supply) -> SupplyRead:
    diets = list(
        await session.scalars(
            select(SupplyDiet)
            .where(SupplyDiet.supply_id == supply.id)
            .order_by(SupplyDiet.lote)
        )
    )
    return SupplyRead(
        id=supply.id,
        name=supply.name,
        price_per_kg=float(supply.price_per_kg),
        legacy_id=supply.legacy_id,
        diets=[
            {"lote": diet.lote, "kg_per_day": float(diet.kg_per_day)} for diet in diets
        ],
    )


@router.get("/dashboard", response_model=DashboardRead)
async def read_dashboard(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    farm: Annotated[Farm, Depends(resolve_current_farm)],
    _: Annotated[User, Depends(require_minimum_role("operator"))],
    measured_on: date | None = Query(default=None),
    lote: str | None = Query(default=None),
    situacao: str | None = Query(default=None),
) -> DashboardRead:
    summary = await build_dashboard(
        session,
        farm_id=farm.id,
        measured_on=measured_on,
        lote=lote,
        situacao=situacao,
    )
    return DashboardRead.model_validate(summary)


@router.get("/supplies", response_model=list[SupplyRead])
async def list_supplies(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    farm: Annotated[Farm, Depends(resolve_current_farm)],
    _: Annotated[User, Depends(require_minimum_role("operator"))],
) -> list[SupplyRead]:
    supplies = list(
        await session.scalars(
            select(Supply).where(Supply.farm_id == farm.id).order_by(Supply.name)
        )
    )
    return [await _read_supply(session, supply) for supply in supplies]


@router.post(
    "/supplies", response_model=SupplyRead, status_code=status.HTTP_201_CREATED
)
async def create_supply(
    payload: SupplyCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    farm: Annotated[Farm, Depends(resolve_current_farm)],
    user: Annotated[User, Depends(require_minimum_role("reviewer"))],
) -> SupplyRead:
    supply = Supply(
        farm_id=farm.id, name=payload.name.strip(), price_per_kg=payload.price_per_kg
    )
    session.add(supply)
    try:
        await session.flush()
    except IntegrityError as error:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Já existe um insumo com o nome {payload.name!r}.",
        ) from error

    session.add(
        SupplyPrice(
            supply_id=supply.id,
            price_per_kg=payload.price_per_kg,
            effective_on=date.today(),
            source="manual",
            recorded_by=user.email,
        )
    )
    session.add(
        AuditEvent(
            farm_id=farm.id,
            actor=user.email,
            action="supply_created",
            entity_type="supply",
            entity_id=supply.id,
            new_value={"name": supply.name, "price_per_kg": payload.price_per_kg},
        )
    )
    await session.commit()
    return await _read_supply(session, supply)


@router.patch("/supplies/{supply_id}", response_model=SupplyRead)
async def update_supply(
    supply_id: UUID,
    payload: SupplyUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    farm: Annotated[Farm, Depends(resolve_current_farm)],
    user: Annotated[User, Depends(require_minimum_role("reviewer"))],
) -> SupplyRead:
    supply = await _supply_or_404(session, supply_id, farm.id)
    previous = {"name": supply.name, "price_per_kg": float(supply.price_per_kg)}

    if payload.name is not None:
        supply.name = payload.name.strip()

    if payload.price_per_kg is not None:
        supply.price_per_kg = payload.price_per_kg
        effective = payload.effective_on or date.today()
        # Preço é evento datado: o anterior fica no histórico. Havendo registro
        # para a mesma data, ele é corrigido em vez de duplicado.
        existing = await session.scalar(
            select(SupplyPrice).where(
                SupplyPrice.supply_id == supply.id,
                SupplyPrice.effective_on == effective,
            )
        )
        if existing is None:
            session.add(
                SupplyPrice(
                    supply_id=supply.id,
                    price_per_kg=payload.price_per_kg,
                    effective_on=effective,
                    source="manual",
                    recorded_by=user.email,
                )
            )
        else:
            existing.price_per_kg = payload.price_per_kg
            existing.recorded_by = user.email

    session.add(
        AuditEvent(
            farm_id=farm.id,
            actor=user.email,
            action="supply_updated",
            entity_type="supply",
            entity_id=supply.id,
            previous_value=previous,
            new_value=payload.model_dump(exclude_unset=True, mode="json"),
        )
    )
    await session.commit()
    return await _read_supply(session, supply)


@router.put("/supplies/{supply_id}/diet", response_model=SupplyRead)
async def set_diet(
    supply_id: UUID,
    payload: DietUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    farm: Annotated[Farm, Depends(resolve_current_farm)],
    user: Annotated[User, Depends(require_minimum_role("reviewer"))],
) -> SupplyRead:
    supply = await _supply_or_404(session, supply_id, farm.id)
    lote = payload.lote.strip()

    diet = await session.scalar(
        select(SupplyDiet).where(
            SupplyDiet.supply_id == supply.id, SupplyDiet.lote == lote
        )
    )
    previous = float(diet.kg_per_day) if diet is not None else None
    if diet is None:
        session.add(
            SupplyDiet(supply_id=supply.id, lote=lote, kg_per_day=payload.kg_per_day)
        )
    else:
        diet.kg_per_day = payload.kg_per_day

    session.add(
        AuditEvent(
            farm_id=farm.id,
            actor=user.email,
            action="supply_diet_changed",
            entity_type="supply",
            entity_id=supply.id,
            previous_value={"lote": lote, "kg_per_day": previous},
            new_value={"lote": lote, "kg_per_day": payload.kg_per_day},
        )
    )
    await session.commit()
    return await _read_supply(session, supply)


@router.patch("/farms/current/milk-price", response_model=MilkPriceUpdate)
async def set_milk_price(
    payload: MilkPriceUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    farm: Annotated[Farm, Depends(resolve_current_farm)],
    user: Annotated[User, Depends(require_minimum_role("reviewer"))],
) -> MilkPriceUpdate:
    previous = (
        float(farm.milk_price_per_liter)
        if farm.milk_price_per_liter is not None
        else None
    )
    farm.milk_price_per_liter = payload.milk_price_per_liter
    session.add(
        AuditEvent(
            farm_id=farm.id,
            actor=user.email,
            action="milk_price_changed",
            entity_type="farm",
            entity_id=farm.id,
            previous_value={"milk_price_per_liter": previous},
            new_value={"milk_price_per_liter": payload.milk_price_per_liter},
        )
    )
    await session.commit()
    return payload
