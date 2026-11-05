"""Contexto de fazenda: a seleção vem do cliente, a autorização vem do banco."""

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from app.core.farm_clock import farm_timezone
from app.core.security import get_current_user
from app.db.models import Farm, FarmMembership, ProducerMembership, User
from app.db.session import get_db_session
from app.services.lot_kind import active_lots
from fastapi import Depends, HTTPException, Request
from sqlalchemy import or_, select
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
            .outerjoin(
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
            .where(
                or_(
                    FarmMembership.user_id.is_not(None),
                    ProducerMembership.user_id.is_not(None),
                )
            )
            .order_by(Farm.name, Farm.id)
        )
    ).all()
    return [
        (farm, "admin" if producer_role else role) for farm, role, producer_role in rows
    ]


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
            else "Escolha a fazenda para continuar.",
        )
    farm, role = farms[0]
    request.state.farm_timezone = farm.timezone
    farm_timezone.set(farm.timezone)
    active_lots.set(farm.lot_settings)
    return FarmAccess(farm, user, role)
