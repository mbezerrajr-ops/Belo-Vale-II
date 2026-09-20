"""Cadastro mestre de animais.

Diferente da ingestão, aqui toda mudança é um ato humano deliberado — e por
isso toda mudança é auditada, com valor anterior e novo.

As regras de identidade valem igual às da ingestão:

- brinco é único por fazenda quando presente, e nulo é um estado válido;
- nome nunca identifica, então nomes repetidos são aceitos sem ressalva;
- lote é histórico: uma mudança encerra a vigência anterior e abre outra, em
  vez de sobrescrever.

Vincular ou trocar o brinco muda a identidade operacional do animal, então
exige evidência declarada — é o caminho pelo qual os 142 registros migrados
sem brinco podem passar a receber matching automático.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Mapping
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.farm_clock import farm_today
from app.db.models import Animal, AnimalLotAssignment, AuditEvent, OfficialMeasurement
from app.services.brinco import normalize_brinco
from app.services.lot_kind import KIND_DIET, classify_lot


class AnimalRegistryError(ValueError):
    """Operação recusada por violar uma regra do cadastro."""


#: Campos que `update_animal` aceita. Identidade (`brinco`, `legacy_id`) e
#: lote ficam de fora de propósito: cada um tem seu caminho explícito.
UPDATABLE_FIELDS = frozenset(
    {
        "name",
        "situacao",
        "status",
        "ultimo_parto",
        "nascimento",
        "peso",
        "numero_legado",
        "observacoes",
    }
)


def _jsonable(values: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Datas e números do cadastro em forma que o JSON da auditoria aceita.

    Sem isto, editar o último parto (uma data) derrubava a gravação da
    auditoria e, com ela, a edição inteira.
    """
    if values is None:
        return None
    return {
        key: value.isoformat() if isinstance(value, date) else
        float(value) if isinstance(value, Decimal) else value
        for key, value in values.items()
    }


def _audit(
    session: AsyncSession,
    *,
    farm_id: UUID,
    actor: str,
    action: str,
    entity_id: UUID,
    previous: Mapping[str, Any] | None = None,
    new: Mapping[str, Any] | None = None,
) -> None:
    session.add(
        AuditEvent(
            farm_id=farm_id,
            actor=actor,
            action=action,
            entity_type="animal",
            entity_id=entity_id,
            previous_value=_jsonable(previous),
            new_value=_jsonable(new),
        )
    )


def _require_readable_brinco(raw: str | None) -> str:
    normalized = normalize_brinco(raw)
    if normalized is None:
        raise AnimalRegistryError(
            f"Brinco ilegível ou vazio: {raw!r}. Um cadastro manual precisa de um "
            "brinco que identifique o animal; deixe-o em branco se ainda não houver."
        )
    return normalized


async def _load_animal(
    session: AsyncSession, *, animal_id: UUID, farm_id: UUID
) -> Animal:
    animal = await session.scalar(
        select(Animal).where(Animal.id == animal_id, Animal.farm_id == farm_id)
    )
    if animal is None:
        raise AnimalRegistryError("Animal não encontrado nesta fazenda.")
    return animal


async def _assert_brinco_is_free(
    session: AsyncSession, *, farm_id: UUID, brinco: str, animal_id: UUID | None
) -> None:
    owner = await session.scalar(
        select(Animal).where(Animal.farm_id == farm_id, Animal.brinco == brinco)
    )
    if owner is not None and owner.id != animal_id:
        raise AnimalRegistryError(
            f"O brinco {brinco!r} já pertence a outro animal ({owner.name or owner.id})."
        )


async def create_animal(
    session: AsyncSession,
    *,
    farm_id: UUID,
    actor: str,
    brinco: str | None = None,
    name: str | None = None,
    legacy_id: str | None = None,
    numero_legado: str | None = None,
    situacao: str | None = None,
    status: str | None = None,
    ultimo_parto: date | None = None,
    nascimento: date | None = None,
    peso: float | None = None,
    observacoes: str | None = None,
    lote: str | None = None,
    lote_valid_from: date | None = None,
) -> Animal:
    normalized = _require_readable_brinco(brinco) if brinco is not None else None
    if normalized is not None:
        await _assert_brinco_is_free(
            session, farm_id=farm_id, brinco=normalized, animal_id=None
        )

    animal = Animal(
        farm_id=farm_id,
        # `identifier` é NOT NULL e único por fazenda, mas não é identidade de
        # negócio: um valor técnico basta.
        identifier=legacy_id or f"a-{uuid4()}",
        legacy_id=legacy_id,
        brinco=normalized,
        brinco_origem=brinco,
        numero_legado=numero_legado,
        name=name,
        situacao=situacao,
        status=status,
        ultimo_parto=ultimo_parto,
        nascimento=nascimento,
        peso=peso,
        observacoes=observacoes,
    )
    session.add(animal)
    await session.flush()

    _audit(
        session,
        farm_id=farm_id,
        actor=actor,
        action="animal_created",
        entity_id=animal.id,
        new={"brinco": normalized, "name": name, "legacy_id": legacy_id},
    )

    if lote:
        session.add(
            AnimalLotAssignment(
                animal_id=animal.id,
                lote=lote,
                kind=classify_lot(lote) or KIND_DIET,
                valid_from=lote_valid_from or farm_today(),
                valid_to=None,
                source="manual",
                reviewed_by=actor,
            )
        )

    await session.commit()
    return animal


async def update_animal(
    session: AsyncSession,
    *,
    animal_id: UUID,
    farm_id: UUID,
    actor: str,
    changes: Mapping[str, Any],
) -> Animal:
    """Altera campos cadastrais. Identidade e lote têm caminhos próprios."""
    rejected = set(changes) - UPDATABLE_FIELDS
    if rejected:
        raise AnimalRegistryError(
            "Campos não alteráveis por esta operação: "
            + ", ".join(sorted(rejected))
            + ". Use a vinculação de brinco ou a mudança de lote."
        )

    animal = await _load_animal(session, animal_id=animal_id, farm_id=farm_id)
    if (
        animal.exited_on is not None
        and "status" in changes
        and changes["status"] != animal.status
    ):
        raise AnimalRegistryError(
            "Este animal teve baixa. Para trazê-lo de volta ao rebanho, "
            "desfaça a baixa informando o motivo."
        )

    previous: dict[str, Any] = {}
    applied: dict[str, Any] = {}
    for field, value in changes.items():
        current = getattr(animal, field)
        if current == value:
            continue
        previous[field] = current
        applied[field] = value
        setattr(animal, field, value)

    if not applied:
        # Nada mudou: não polui a auditoria com um evento vazio.
        return animal

    _audit(
        session,
        farm_id=farm_id,
        actor=actor,
        action="animal_updated",
        entity_id=animal.id,
        previous=previous,
        new=applied,
    )
    await session.commit()
    return animal


async def link_brinco(
    session: AsyncSession,
    *,
    animal_id: UUID,
    farm_id: UUID,
    actor: str,
    brinco: str,
    evidence: str,
) -> Animal:
    """Vincula ou substitui o brinco de um animal.

    Muda a identidade operacional: a partir daqui o animal passa a receber (ou
    deixa de receber) matching automático. Por isso exige evidência declarada.
    """
    if not evidence or not evidence.strip():
        raise AnimalRegistryError(
            "Vincular um brinco muda a identidade operacional do animal: "
            "informe a evidência que sustenta a decisão."
        )

    normalized = _require_readable_brinco(brinco)
    animal = await _load_animal(session, animal_id=animal_id, farm_id=farm_id)
    await _assert_brinco_is_free(
        session, farm_id=farm_id, brinco=normalized, animal_id=animal.id
    )

    previous = {"brinco": animal.brinco, "brinco_origem": animal.brinco_origem}
    animal.brinco = normalized
    animal.brinco_origem = brinco

    _audit(
        session,
        farm_id=farm_id,
        actor=actor,
        action="animal_brinco_linked",
        entity_id=animal.id,
        previous=previous,
        new={
            "brinco": normalized,
            "brinco_origem": brinco,
            "evidence": evidence.strip(),
        },
    )
    await session.commit()
    return animal


async def unlink_brinco(
    session: AsyncSession,
    *,
    animal_id: UUID,
    farm_id: UUID,
    actor: str,
    evidence: str,
) -> Animal:
    """Tira o brinco de um animal: ele volta a ficar "sem brinco".

    Existe para o brinco que caiu da orelha e para o que foi atribuído à vaca
    errada — o número precisa ficar livre para quem é de direito. Como
    `link_brinco`, muda a identidade operacional: a partir daqui o animal
    deixa de receber matching automático, e por isso exige evidência.
    """
    if not evidence or not evidence.strip():
        raise AnimalRegistryError(
            "Tirar o brinco muda a identidade operacional do animal: "
            "informe a evidência que sustenta a decisão."
        )

    animal = await _load_animal(session, animal_id=animal_id, farm_id=farm_id)
    previous = {"brinco": animal.brinco, "brinco_origem": animal.brinco_origem}
    animal.brinco = None
    animal.brinco_origem = None

    _audit(
        session,
        farm_id=farm_id,
        actor=actor,
        action="animal_brinco_unlinked",
        entity_id=animal.id,
        previous=previous,
        new={"brinco": None, "evidence": evidence.strip()},
    )
    await session.commit()
    return animal


async def assign_lot(
    session: AsyncSession,
    *,
    animal_id: UUID,
    farm_id: UUID,
    actor: str,
    lote: str,
    valid_from: date,
    source: str = "manual",
    kind: str | None = None,
) -> AnimalLotAssignment | None:
    """Registra uma mudança de lote como evento temporal.

    Encerra a vigência anterior na véspera e abre a nova. Devolve ``None``
    quando o animal já está no lote informado — repetir a informação não é
    uma mudança.

    `kind` separa lote de ordenha de grupo de manejo; quando omitido, é
    deduzido do nome. Cada tipo tem sua própria vigência, então mudar de
    piquete não tira a vaca do lote de ordenha.
    """
    if not lote or not lote.strip():
        raise AnimalRegistryError("Informe o lote.")

    animal = await _load_animal(session, animal_id=animal_id, farm_id=farm_id)
    if animal.exited_on is not None:
        raise AnimalRegistryError(
            f"Este animal teve baixa em {animal.exited_on:%d/%m/%Y} e não pode "
            "mudar de lote."
        )
    lote = lote.strip()
    kind = kind or classify_lot(lote) or KIND_DIET

    current = await session.scalar(
        select(AnimalLotAssignment).where(
            AnimalLotAssignment.animal_id == animal.id,
            AnimalLotAssignment.kind == kind,
            AnimalLotAssignment.valid_to.is_(None),
        )
    )

    if current is not None:
        if current.lote == lote:
            return None
        if valid_from <= current.valid_from:
            raise AnimalRegistryError(
                f"A vigência do novo lote ({valid_from.isoformat()}) precisa ser "
                f"posterior ao início da atual ({current.valid_from.isoformat()}). "
                "Corrija a data ou ajuste o registro anterior explicitamente."
            )
        current.valid_to = valid_from - timedelta(days=1)

    assignment = AnimalLotAssignment(
        animal_id=animal.id,
        lote=lote,
        kind=kind,
        valid_from=valid_from,
        valid_to=None,
        source=source,
        reviewed_by=actor,
    )
    session.add(assignment)

    _audit(
        session,
        farm_id=farm_id,
        actor=actor,
        action="animal_lot_changed",
        entity_id=animal.id,
        previous={"lote": current.lote, "kind": kind} if current is not None else None,
        new={"lote": lote, "kind": kind, "valid_from": valid_from.isoformat()},
    )
    await session.commit()
    return assignment


async def current_lot(
    session: AsyncSession, *, animal_id: UUID, kind: str = KIND_DIET
) -> AnimalLotAssignment | None:
    """Lotação vigente de um tipo. Por padrão, o lote de ordenha."""
    return await session.scalar(
        select(AnimalLotAssignment).where(
            AnimalLotAssignment.animal_id == animal_id,
            AnimalLotAssignment.kind == kind,
            AnimalLotAssignment.valid_to.is_(None),
        )
    )


async def lot_history(
    session: AsyncSession, *, animal_id: UUID
) -> list[AnimalLotAssignment]:
    return list(
        await session.scalars(
            select(AnimalLotAssignment)
            .where(AnimalLotAssignment.animal_id == animal_id)
            .order_by(AnimalLotAssignment.valid_from)
        )
    )


#: `status` legado. A plataforma antiga só conhecia estes dois valores.
STATUS_ACTIVE = "Ativo"
STATUS_INACTIVE = "Inativo"


async def register_exit(
    session: AsyncSession,
    *,
    animal_id: UUID,
    farm_id: UUID,
    actor: str,
    exited_on: date,
    reason: str,
    notes: str | None = None,
) -> Animal:
    """Tira o animal do rebanho: venda, morte, descarte, doação.

    Encerra as lotações vigentes no dia da baixa e nunca apaga produção. Uma
    leitura depois da data da baixa significa que uma das duas datas está
    errada, e o sistema não escolhe qual: recusa e diz o porquê.
    """
    if exited_on > farm_today():
        raise AnimalRegistryError("A data da baixa não pode ser no futuro.")

    animal = await _load_animal(session, animal_id=animal_id, farm_id=farm_id)
    if animal.exited_on is not None:
        raise AnimalRegistryError(
            f"Este animal já teve baixa em {animal.exited_on:%d/%m/%Y}."
        )

    later = await session.scalar(
        select(OfficialMeasurement.measured_on)
        .where(
            OfficialMeasurement.animal_id == animal.id,
            OfficialMeasurement.status == "active",
            OfficialMeasurement.measured_on > exited_on,
        )
        .order_by(OfficialMeasurement.measured_on.desc())
        .limit(1)
    )
    if later is not None:
        raise AnimalRegistryError(
            f"Há produção lançada em {later:%d/%m/%Y}, depois da data da baixa. "
            "Confira a data da baixa ou corrija o lançamento antes."
        )

    open_lots = list(
        await session.scalars(
            select(AnimalLotAssignment).where(
                AnimalLotAssignment.animal_id == animal.id,
                AnimalLotAssignment.valid_to.is_(None),
            )
        )
    )
    for assignment in open_lots:
        if assignment.valid_from > exited_on:
            raise AnimalRegistryError(
                f"O animal entrou em {assignment.lote} em "
                f"{assignment.valid_from:%d/%m/%Y}, depois da data da baixa."
            )
        assignment.valid_to = exited_on

    previous = {
        "status": animal.status,
        "lotes": [a.lote for a in open_lots],
    }
    animal.exited_on = exited_on
    animal.exit_reason = reason
    animal.exit_notes = notes.strip() if notes and notes.strip() else None
    animal.status = STATUS_INACTIVE

    _audit(
        session,
        farm_id=farm_id,
        actor=actor,
        action="animal_exited",
        entity_id=animal.id,
        previous=previous,
        new={
            "exited_on": exited_on.isoformat(),
            "reason": reason,
            "notes": animal.exit_notes,
        },
    )
    await session.commit()
    return animal


async def undo_exit(
    session: AsyncSession,
    *,
    animal_id: UUID,
    farm_id: UUID,
    actor: str,
    reason: str,
) -> Animal:
    """Desfaz uma baixa registrada por engano.

    Não reabre as lotações encerradas: o animal volta ao rebanho sem lote, e
    quem desfaz decide onde ele está hoje. Reabrir sozinho afirmaria uma
    lotação que ninguém confirmou.
    """
    animal = await _load_animal(session, animal_id=animal_id, farm_id=farm_id)
    if animal.exited_on is None:
        raise AnimalRegistryError("Este animal não tem baixa para desfazer.")

    previous = {
        "exited_on": animal.exited_on.isoformat(),
        "exit_reason": animal.exit_reason,
        "exit_notes": animal.exit_notes,
    }
    animal.exited_on = None
    animal.exit_reason = None
    animal.exit_notes = None
    animal.status = STATUS_ACTIVE

    _audit(
        session,
        farm_id=farm_id,
        actor=actor,
        action="animal_exit_undone",
        entity_id=animal.id,
        previous=previous,
        new={"reason": reason},
    )
    await session.commit()
    return animal
