"""Gestão de contas de usuário.

Até aqui só existia o bootstrap do primeiro administrador, o que impedia
qualquer funcionário de entrar no sistema. Estes endpoints permitem ao dono da
fazenda criar contas, desativar quem saiu e ajustar papéis.

Duas proteções acompanham o CRUD e valem tanto quanto ele:

- um administrador não consegue se desativar nem se rebaixar, então não é
  possível ficar sem ninguém que administre o sistema;
- nenhuma resposta devolve hash de senha, porque os modelos de saída declaram
  campo a campo em vez de serializar o objeto inteiro.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.password_policy import PasswordPolicyError, validate_password
from app.core.temporary_password import (
    TEMPORARY_PASSWORD_TTL,
    generate_temporary_password,
)
from app.core.security import (
    get_authenticated_user,
    hash_password,
    require_minimum_role,
    verify_password,
)
from app.db.models import AuditEvent, User
from app.db.session import get_db_session
from app.services.refresh_tokens import revoke_all_for_user
from app.schemas.users import (
    PasswordChange,
    PasswordResetRead,
    UserCreate,
    UserPage,
    UserRead,
    UserUpdate,
)

router = APIRouter(prefix="/api/users", tags=["users"])


def _policy_error(error: PasswordPolicyError) -> HTTPException:
    # 422: a requisição está bem formada, mas o valor não é aceitável. A
    # mensagem é escrita para o usuário final e nunca inclui a senha.
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
    )


def _audit(
    session: AsyncSession,
    *,
    actor: str,
    action: str,
    entity_id: UUID,
    previous: dict | None = None,
    new: dict | None = None,
) -> None:
    session.add(
        AuditEvent(
            farm_id=None,
            actor=actor,
            action=action,
            entity_type="user",
            entity_id=entity_id,
            previous_value=previous,
            new_value=new,
        )
    )


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    admin: Annotated[User, Depends(require_minimum_role("admin"))],
) -> User:
    email = payload.email.strip().lower()
    try:
        validate_password(payload.password, email=email)
    except PasswordPolicyError as error:
        raise _policy_error(error) from error

    existing = await session.scalar(
        select(User).where(func.lower(User.email) == email)
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe uma conta com este e-mail.",
        )

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        role=payload.role,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    _audit(
        session,
        actor=admin.email,
        action="user_created",
        entity_id=user.id,
        new={"email": email, "role": payload.role},
    )
    await session.commit()
    return user


@router.get("", response_model=UserPage)
async def list_users(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[User, Depends(require_minimum_role("admin"))],
) -> UserPage:
    users = list(await session.scalars(select(User).order_by(User.email)))
    return UserPage(
        items=[UserRead.model_validate(user) for user in users], total=len(users)
    )


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: UUID,
    payload: UserUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    admin: Annotated[User, Depends(require_minimum_role("admin"))],
) -> User:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Nada a alterar."
        )

    user = await session.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conta não encontrada."
        )

    # Sem esta guarda, um administrador distraído pode remover o próprio
    # acesso e deixar o sistema sem quem o administre.
    if user.id == admin.id:
        if changes.get("is_active") is False:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Você não pode desativar a sua própria conta.",
            )
        if "role" in changes and changes["role"] != user.role:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Você não pode mudar o papel da sua própria conta. "
                    "Peça a outro administrador."
                ),
            )

    previous = {key: getattr(user, key) for key in changes}
    for key, value in changes.items():
        setattr(user, key, value)

    _audit(
        session,
        actor=admin.email,
        action="user_updated",
        entity_id=user.id,
        previous=previous,
        new=changes,
    )
    await session.commit()
    return user


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_own_password(
    payload: PasswordChange,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_authenticated_user)],
) -> Response:
    """Trocar a própria senha não exige papel elevado.

    É também a saída de quem entrou com senha provisória, por isso aceita uma
    conta que ainda precisa trocar a senha.
    """
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Senha atual incorreta."
        )
    if payload.new_password == payload.current_password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A nova senha precisa ser diferente da atual.",
        )
    try:
        validate_password(payload.new_password, email=user.email)
    except PasswordPolicyError as error:
        raise _policy_error(error) from error

    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    user.password_expires_at = None
    # A auditoria registra a troca, nunca o valor.
    _audit(
        session,
        actor=user.email,
        action="user_password_changed",
        entity_id=user.id,
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{user_id}/password-reset", response_model=PasswordResetRead)
async def reset_password(
    user_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    admin: Annotated[User, Depends(require_minimum_role("admin"))],
) -> PasswordResetRead:
    """Gera uma senha provisória para quem esqueceu a sua.

    A senha é gerada aqui, não escolhida pelo administrador, expira sozinha e
    só serve para escolher outra. As sessões abertas da conta caem: quem pede
    a redefinição pode estar justamente perdendo o controle dela.
    """
    user = await session.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conta não encontrada."
        )
    if user.id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Para a sua própria senha, use \"Trocar senha\".",
        )

    temporary = generate_temporary_password()
    expires_at = datetime.now(timezone.utc) + TEMPORARY_PASSWORD_TTL
    user.password_hash = hash_password(temporary)
    user.must_change_password = True
    user.password_expires_at = expires_at
    # A auditoria registra quem redefiniu e até quando vale, nunca o valor.
    _audit(
        session,
        actor=admin.email,
        action="user_password_reset",
        entity_id=user.id,
        new={"expires_at": expires_at.isoformat()},
    )
    # Por último: a revogação faz o commit, e senha, auditoria e sessões
    # derrubadas entram juntos — nunca uma senha trocada sem registro.
    await revoke_all_for_user(session, user_id=user.id, reason="password_reset")
    return PasswordResetRead(temporary_password=temporary, expires_at=expires_at)
