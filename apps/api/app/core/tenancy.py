"""Cada usuário acessa uma única fazenda, definida pelo vínculo no banco."""

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from app.core.farm_clock import farm_timezone
from app.core.security import get_current_user
from app.db.models import Farm, FarmMembership, ProducerMembership, User
from app.db.session import get_db_session
from app.services.lot_kind import active_lots
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class FarmAccess:
    farm: Farm
    user: User
    role: str

    @property
    def id(self):
        return self.user.id

    @property
    def email(self):
        return self.user.email


async def available_farms(session: AsyncSession, user: User) -> list[tuple[Farm, str]]:
    rows = (
        await session.execute(
            select(Farm, FarmMembership.role, ProducerMembership.role)
            .join(
                FarmMembership,
                (FarmMembership.farm_id == Farm.id)
                & (FarmMembership.user_id == user.id)
                & FarmMembership.is_active,
            )
            .outerjoin(
                ProducerMembership,
                (ProducerMembership.producer_account_id == Farm.producer_account_id)
                & (ProducerMembership.user_id == user.id),
            )
            .order_by(Farm.name, Farm.id)
        )
    ).all()
    if len(rows) > 1:
        raise HTTPException(
            409,
            "A conta precisa estar vinculada a uma única fazenda. Fale com o administrador.",
        )
    return [
        (farm, "admin" if producer_role else role) for farm, role, producer_role in rows
    ]


async def ensure_single_farm(
    session: AsyncSession, user_id: UUID, farm_id: UUID | None = None
):
    # Serializa criações e reativações para a mesma identidade.
    await session.scalar(select(User.id).where(User.id == user_id).with_for_update())
    query = select(FarmMembership.farm_id).where(
        FarmMembership.user_id == user_id, FarmMembership.is_active
    )
    if farm_id is not None:
        query = query.where(FarmMembership.farm_id != farm_id)
    if await session.scalar(query.limit(1)) is not None:
        raise HTTPException(409, "Esta conta já está vinculada a uma fazenda.")


async def get_farm_access(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
) -> FarmAccess:
    selection = request.headers.get("X-Farm-ID")
    if selection:
        try:
            selected_id = UUID(selection)
        except ValueError:
            raise HTTPException(400, "Seleção de fazenda inválida.")
    else:
        selected_id = None
    farms = await available_farms(session, user)
    if selected_id:
        for farm, role in farms:
            if farm.id == selected_id:
                request.state.farm_timezone = farm.timezone
                farm_timezone.set(farm.timezone)
                active_lots.set(farm.lot_settings)
                return FarmAccess(farm, user, role)
        raise HTTPException(404, "Fazenda não encontrada ou acesso removido.")
    if len(farms) != 1:
        raise HTTPException(
            409,
            "Nenhuma fazenda disponível. Cadastre uma fazenda ou aceite um convite."
            if not farms
            else "A conta precisa estar vinculada a uma única fazenda.",
        )
    farm, role = farms[0]
    request.state.farm_timezone = farm.timezone
    farm_timezone.set(farm.timezone)
    active_lots.set(farm.lot_settings)
    return FarmAccess(farm, user, role)
