"""Entrada de produtores, fazendas e convites sem autorização global implícita."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import urlencode
from uuid import UUID

from app.core.config import Settings, get_settings
from app.core.login_throttle import LoginThrottle, get_login_throttle
from app.core.password_policy import PasswordPolicyError, validate_password
from app.core.security import (
    get_current_user,
    hash_password,
    require_minimum_role,
    verify_password,
)
from app.core.tenancy import FarmAccess, available_farms, ensure_single_farm
from app.db.models import (
    AccountToken,
    AuditEvent,
    Farm,
    FarmMembership,
    ProducerAccount,
    ProducerMembership,
    User,
)
from app.db.session import get_db_session
from app.schemas.tenancy import (
    EmailInput,
    FarmSettings,
    Invitation,
    NewFarm,
    ProducerCreate,
    RecoverPassword,
    Registration,
    TokenInput,
    TransferOwnership,
)
from app.services.account_mail import Mailer, get_mailer
from app.services.refresh_tokens import revoke_all_for_user
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

router = APIRouter(prefix="/api", tags=["producers"])
DB = Annotated[AsyncSession, Depends(get_db_session)]
Identity = Annotated[User, Depends(get_current_user)]
Mail = Annotated[Mailer, Depends(get_mailer)]
Config = Annotated[Settings, Depends(get_settings)]
AdminAccess = Annotated[FarmAccess, Depends(require_minimum_role("admin"))]


def password_policy(password: str, email: str):
    try:
        validate_password(password, email=email)
    except PasswordPolicyError as error:
        raise HTTPException(422, str(error)) from error


async def public_rate_limit(
    request: Request,
    session: DB,
    throttle: Annotated[LoginThrottle, Depends(get_login_throttle)],
):
    host = request.client.host if request.client else "unknown"
    origin = f"accounts:{request.url.path}:{host}"
    key = origin
    retry = await throttle.check(key, origin)
    if retry is not None:
        raise HTTPException(
            429,
            "Muitas solicitações. Tente mais tarde.",
            headers={"Retry-After": str(retry)},
        )
    await throttle.record_failure(key, origin)


def audit(session, user, farm_id, action, entity_id, previous=None, new=None):
    session.add(
        AuditEvent(
            farm_id=farm_id,
            actor=user.email,
            action=action,
            entity_type="membership",
            entity_id=entity_id,
            previous_value=previous,
            new_value=new,
        )
    )


async def send_token(
    session: DB,
    mail: Mailer,
    settings: Settings,
    *,
    user: User,
    purpose: str,
    farm_id=None,
    email=None,
    role=None,
):
    raw = secrets.token_urlsafe(32)
    # Um novo link invalida os anteriores da mesma ação/conta/fazenda.
    await session.execute(
        update(AccountToken)
        .where(
            AccountToken.email == (email or user.email),
            AccountToken.purpose == purpose,
            AccountToken.farm_id == farm_id,
            AccountToken.consumed_at.is_(None),
        )
        .values(consumed_at=datetime.now(UTC))
    )
    record = AccountToken(
        user_id=user.id,
        farm_id=farm_id,
        email=email or user.email,
        purpose=purpose,
        role=role,
        token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        expires_at=datetime.now(UTC) + timedelta(hours=24 if purpose != "reset" else 1),
    )
    session.add(record)
    await session.flush()
    labels = {
        "verify": "Confirme seu e-mail",
        "reset": "Recupere seu acesso",
        "invite": "Convite para administrar uma fazenda",
    }
    link = (
        settings.public_app_url.rstrip("/")
        + "/?"
        + urlencode({"action": purpose, "token": raw})
    )
    await run_in_threadpool(
        mail.send,
        record.email,
        labels[purpose],
        f"{labels[purpose]}\n\nAbra o aplicativo pelo link:\n{link}\n\nSe você não solicitou esta ação, ignore esta mensagem.",
    )


async def consume_token(session: DB, raw: str, purpose: str):
    record = await session.scalar(
        select(AccountToken)
        .where(
            AccountToken.token_hash == hashlib.sha256(raw.encode()).hexdigest(),
            AccountToken.purpose == purpose,
        )
        .with_for_update()
    )
    if (
        record is None
        or record.consumed_at is not None
        or record.expires_at <= datetime.now(UTC)
    ):
        raise HTTPException(400, "Link inválido, vencido ou já utilizado.")
    return record


@router.post(
    "/auth/register", status_code=202, dependencies=[Depends(public_rate_limit)]
)
async def register(payload: Registration, session: DB, mail: Mail, settings: Config):
    password_policy(payload.password, payload.email)
    user = await session.scalar(
        select(User).where(func.lower(User.email) == payload.email)
    )
    if user is None:
        user = User(
            email=payload.email,
            password_hash=hash_password(payload.password),
            role="operator",
            is_active=True,
            email_verification_required=True,
        )
        account = ProducerAccount(name=payload.producer_name.strip())
        session.add_all([user, account])
        await session.flush()
        farm = Farm(
            name=payload.farm_name.strip(),
            producer_account_id=account.id,
            timezone="America/Recife",
            lot_settings=[],
        )
        session.add(farm)
        await session.flush()
        session.add_all(
            [
                ProducerMembership(
                    producer_account_id=account.id, user_id=user.id, role="owner"
                ),
                FarmMembership(farm_id=farm.id, user_id=user.id, role="admin"),
            ]
        )
    if user.email_verified_at is None:
        await send_token(session, mail, settings, user=user, purpose="verify")
    await session.commit()
    return {
        "message": "Se o cadastro puder prosseguir, você receberá um e-mail com as instruções."
    }


@router.post("/auth/verify", dependencies=[Depends(public_rate_limit)])
async def verify(payload: TokenInput, session: DB):
    record = await consume_token(session, payload.token, "verify")
    user = await session.get(User, record.user_id)
    if user is None or not user.is_active:
        raise HTTPException(400, "Conta indisponível.")
    user.email_verified_at = record.consumed_at = datetime.now(UTC)
    await session.commit()
    return {"message": "E-mail confirmado. Entre para administrar sua fazenda."}


@router.post(
    "/auth/forgot-password", status_code=202, dependencies=[Depends(public_rate_limit)]
)
async def forgot_password(
    payload: EmailInput, session: DB, mail: Mail, settings: Config
):
    user = await session.scalar(
        select(User).where(func.lower(User.email) == payload.email, User.is_active)
    )
    if user:
        await send_token(session, mail, settings, user=user, purpose="reset")
        await session.commit()
    return {"message": "Se a conta existir, você receberá as instruções no e-mail."}


@router.post("/auth/recover-password", dependencies=[Depends(public_rate_limit)])
async def recover_password(payload: RecoverPassword, session: DB):
    record = await consume_token(session, payload.token, "reset")
    user = await session.get(User, record.user_id)
    if user is None or not user.is_active:
        raise HTTPException(400, "Conta indisponível.")
    password_policy(payload.password, user.email)
    user.password_hash = hash_password(payload.password)
    user.must_change_password = False
    user.password_expires_at = None
    user.email_verified_at = datetime.now(UTC)
    record.consumed_at = datetime.now(UTC)
    await session.execute(
        update(AccountToken)
        .where(
            AccountToken.user_id == user.id,
            AccountToken.purpose == "reset",
            AccountToken.consumed_at.is_(None),
        )
        .values(consumed_at=record.consumed_at)
    )
    await revoke_all_for_user(session, user_id=user.id, reason="password_recovery")
    return {"message": "Senha alterada. Entre novamente."}


def farm_output(farm: Farm, role: str):
    return {
        "id": str(farm.id),
        "name": farm.name,
        "code": farm.code,
        "producer_account_id": str(farm.producer_account_id)
        if farm.producer_account_id
        else None,
        "timezone": farm.timezone,
        "lot_settings": farm.lot_settings,
        "milk_price_per_liter": float(farm.milk_price_per_liter)
        if farm.milk_price_per_liter is not None
        else None,
        "role": role,
    }


@router.get("/farms")
async def list_farms(session: DB, user: Identity):
    return [
        farm_output(farm, role) for farm, role in await available_farms(session, user)
    ]


@router.get("/producer-accounts")
async def list_accounts(session: DB, user: Identity):
    rows = (
        await session.execute(
            select(ProducerAccount, ProducerMembership.role)
            .join(
                ProducerMembership,
                ProducerMembership.producer_account_id == ProducerAccount.id,
            )
            .where(ProducerMembership.user_id == user.id)
        )
    ).all()
    return [
        {"id": str(account.id), "name": account.name, "role": role}
        for account, role in rows
    ]


@router.post("/producer-accounts", status_code=201)
async def new_account(payload: ProducerCreate, session: DB, user: Identity):
    if user.email_verified_at is None:
        raise HTTPException(
            403,
            "Confirme seu e-mail pelo cadastro ou pela recuperação de acesso antes de criar uma conta produtora.",
        )
    await ensure_single_farm(session, user.id)
    if await session.scalar(
        select(ProducerMembership.user_id)
        .where(ProducerMembership.user_id == user.id)
        .limit(1)
    ):
        raise HTTPException(409, "Esta conta já possui um cadastro de produtor.")
    if not payload.name.strip():
        raise HTTPException(422, "Informe o nome da conta produtora.")
    account = ProducerAccount(name=payload.name.strip())
    session.add(account)
    await session.flush()
    session.add(
        ProducerMembership(
            producer_account_id=account.id, user_id=user.id, role="owner"
        )
    )
    await session.commit()
    return {"id": str(account.id), "name": account.name, "role": "owner"}


async def producer_admin(session, user, account_id, *, owner_only=False):
    membership = await session.get(ProducerMembership, (account_id, user.id))
    if membership is None or (owner_only and membership.role != "owner"):
        raise HTTPException(
            403, "Somente o responsável pela conta produtora pode realizar esta ação."
        )
    return membership


@router.post("/farms/new", status_code=201)
async def new_farm(payload: NewFarm, session: DB, user: Identity):
    await producer_admin(session, user, payload.producer_account_id)
    await ensure_single_farm(session, user.id)
    await session.scalar(
        select(ProducerAccount.id)
        .where(ProducerAccount.id == payload.producer_account_id)
        .with_for_update()
    )
    if await session.scalar(
        select(Farm.id)
        .where(Farm.producer_account_id == payload.producer_account_id)
        .limit(1)
    ):
        raise HTTPException(409, "Este produtor já possui sua fazenda cadastrada.")
    farm = Farm(
        **payload.model_dump(exclude={"lot_settings"}),
        lot_settings=[lot.model_dump() for lot in payload.lot_settings],
    )
    session.add(farm)
    await session.flush()
    session.add(FarmMembership(farm_id=farm.id, user_id=user.id, role="admin"))
    audit(session, user, farm.id, "farm_created", farm.id)
    await session.commit()
    return farm_output(farm, "admin")


@router.patch("/farms/current")
async def configure_farm(payload: FarmSettings, session: DB, access: AdminAccess):
    farm = access.farm
    from app.db.models import Animal, AnimalLotAssignment

    open_lots = (
        await session.execute(
            select(AnimalLotAssignment.lote, AnimalLotAssignment.kind)
            .join(Animal, Animal.id == AnimalLotAssignment.animal_id)
            .where(Animal.farm_id == farm.id, AnimalLotAssignment.valid_to.is_(None))
        )
    ).all()
    configured = {lot.name.casefold(): lot.kind for lot in payload.lot_settings}
    if any(configured.get(name.casefold()) != kind for name, kind in open_lots):
        raise HTTPException(
            409, "Mova os animais antes de remover ou mudar o tipo de um lote em uso."
        )
    previous = farm_output(farm, access.role)
    for key, value in payload.model_dump().items():
        setattr(farm, key, value)
    audit(
        session,
        access,
        farm.id,
        "farm_configured",
        farm.id,
        previous,
        farm_output(farm, access.role),
    )
    await session.commit()
    return farm_output(farm, access.role)


@router.post("/farms/current/invitations", status_code=201)
async def invite(
    payload: Invitation,
    session: DB,
    mail: Mail,
    settings: Config,
    access: AdminAccess,
):
    await send_token(
        session,
        mail,
        settings,
        user=access.user,
        purpose="invite",
        farm_id=access.farm.id,
        email=payload.email,
        role=payload.role,
    )
    audit(
        session,
        access,
        access.farm.id,
        "member_invited",
        access.farm.id,
        new={"email": payload.email, "role": payload.role},
    )
    await session.commit()
    return {"message": "Convite enviado por e-mail."}


@router.post("/invitations/accept")
async def accept_invitation(payload: TokenInput, session: DB, user: Identity):
    record = await consume_token(session, payload.token, "invite")
    if record.email.lower() != user.email.lower():
        raise HTTPException(403, "Entre com o e-mail que recebeu o convite.")
    inviter = await session.get(User, record.user_id)
    allowed = (
        await available_farms(session, inviter) if inviter and inviter.is_active else []
    )
    if not any(farm.id == record.farm_id and role == "admin" for farm, role in allowed):
        raise HTTPException(403, "Este convite não está mais autorizado.")
    await ensure_single_farm(session, user.id, record.farm_id)
    membership = await session.get(FarmMembership, (record.farm_id, user.id))
    if membership is None:
        membership = FarmMembership(
            farm_id=record.farm_id, user_id=user.id, role=record.role
        )
        session.add(membership)
    else:
        membership.role, membership.is_active = record.role, True
    record.consumed_at = datetime.now(UTC)
    user.email_verified_at = user.email_verified_at or record.consumed_at
    audit(
        session,
        user,
        record.farm_id,
        "invitation_accepted",
        user.id,
        new={"role": record.role},
    )
    await session.commit()
    return {"message": "Convite aceito.", "farm_id": str(record.farm_id)}


@router.delete("/farms/current/invitations/{invitation_id}", status_code=204)
async def cancel_invitation(invitation_id: UUID, session: DB, access: AdminAccess):
    record = await session.get(AccountToken, invitation_id)
    if record is None or record.purpose != "invite" or record.farm_id != access.farm.id:
        raise HTTPException(404, "Convite não encontrado.")
    record.consumed_at = datetime.now(UTC)
    await session.commit()


@router.get("/farms/current/invitations")
async def list_invitations(session: DB, access: AdminAccess):
    rows = await session.scalars(
        select(AccountToken).where(
            AccountToken.farm_id == access.farm.id,
            AccountToken.purpose == "invite",
            AccountToken.consumed_at.is_(None),
            AccountToken.expires_at > datetime.now(UTC),
        )
    )
    return [
        {
            "id": str(row.id),
            "email": row.email,
            "role": row.role,
            "expires_at": row.expires_at,
        }
        for row in rows
    ]


@router.post("/producer-accounts/{account_id}/transfer")
async def transfer_owner(
    account_id: UUID, payload: TransferOwnership, session: DB, user: Identity
):
    account = await session.scalar(
        select(ProducerAccount)
        .where(ProducerAccount.id == account_id)
        .with_for_update()
    )
    if account is None:
        raise HTTPException(404, "Conta produtora não encontrada.")
    previous = await producer_admin(session, user, account_id, owner_only=True)
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(403, "Senha atual incorreta.")
    if payload.user_id == user.id:
        raise HTTPException(409, "A conta já pertence a você.")
    target = await session.get(User, payload.user_id)
    link = await session.scalar(
        select(FarmMembership)
        .join(Farm, Farm.id == FarmMembership.farm_id)
        .where(
            Farm.producer_account_id == account_id,
            FarmMembership.user_id == payload.user_id,
            FarmMembership.is_active,
        )
        .limit(1)
    )
    if target is None or not target.is_active or link is None:
        raise HTTPException(404, "Escolha um integrante ativo da sua equipe.")
    previous.role = "admin"
    await session.flush()
    membership = await session.get(ProducerMembership, (account_id, target.id))
    if membership:
        membership.role = "owner"
    else:
        session.add(
            ProducerMembership(
                producer_account_id=account_id, user_id=target.id, role="owner"
            )
        )
    audit(
        session,
        user,
        link.farm_id,
        "ownership_transferred",
        account_id,
        {"owner": str(user.id)},
        {"owner": str(target.id)},
    )
    await session.commit()
    return {
        "message": "Responsabilidade transferida. Seu acesso administrativo foi mantido."
    }


@router.get("/producer-accounts/{account_id}/usage")
async def account_usage(account_id: UUID, session: DB, user: Identity):
    await producer_admin(session, user, account_id)
    from app.services.tenant_limits import usage

    return await usage(session, account_id)


@router.get("/producer-accounts/{account_id}/members")
async def list_account_members(account_id: UUID, session: DB, user: Identity):
    await producer_admin(session, user, account_id, owner_only=True)
    rows = (
        await session.execute(
            select(User, ProducerMembership.role)
            .join(ProducerMembership, ProducerMembership.user_id == User.id)
            .where(ProducerMembership.producer_account_id == account_id)
        )
    ).all()
    return [
        {"id": str(member.id), "email": member.email, "role": role}
        for member, role in rows
    ]


@router.delete("/producer-accounts/{account_id}/members/{user_id}", status_code=204)
async def remove_account_admin(
    account_id: UUID, user_id: UUID, session: DB, user: Identity
):
    await producer_admin(session, user, account_id, owner_only=True)
    link = await session.get(ProducerMembership, (account_id, user_id))
    if link is None:
        raise HTTPException(404, "Integrante não encontrado.")
    if link.role == "owner" or user_id == user.id:
        raise HTTPException(
            409, "Transfira a responsabilidade antes de remover o proprietário."
        )
    await session.delete(link)
    await session.execute(
        update(FarmMembership)
        .where(
            FarmMembership.user_id == user_id,
            FarmMembership.farm_id.in_(
                select(Farm.id).where(Farm.producer_account_id == account_id)
            ),
        )
        .values(is_active=False)
    )
    await session.commit()
