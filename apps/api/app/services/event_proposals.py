"""Propostas de eventos: criar a partir de uma leitura, listar e decidir.

Três regras sustentam a caixa de revisão:

1. **Só o brinco associa.** O nome lido ("a Ágata deu 20 litros") nunca
   escolhe o animal; aparece como sugestão, e quem revisa escolhe.
2. **Aprovar usa as regras que já existem.** Baixa, lote e cadastro passam
   pelos serviços do cadastro, com as mesmas recusas; produção segue a mesma
   política do lançamento (valor diferente do já lançado exige motivo).
3. **O que foi lido não muda.** `raw_fields` fica como veio; a correção de
   quem revisa vai para `applied_payload`. Decidida, a proposta é imutável
   (trigger no banco).

Nenhuma função aqui faz commit, exceto quando delega a um serviço do cadastro
que já o faz — por isso a proposta é marcada como aprovada *antes* de
aplicar: o commit do serviço leva as duas coisas juntas, e uma recusa dele
desfaz as duas.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.farm_clock import farm_today
from app.db.models import (
    Animal,
    AuditEvent,
    EventProposal,
    EventProposalSource,
    OfficialMeasurement,
    User,
)
from app.services.animal_registry import (
    assign_lot,
    current_lot,
    register_exit,
    update_animal,
)
from app.services.brinco import normalize_brinco
from app.services.event_extraction import EventExtraction
from app.services.event_normalization import normalize_event
from app.services.lot_kind import KIND_DIET, KIND_MANAGEMENT
from app.services.production_entry import MAX_LITERS, diet_lot_on, producao_of

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"

SOURCE_KINDS = ("photo", "audio", "text")


class ProposalError(ValueError):
    """Decisão recusada. A mensagem é para quem revisa."""


class ProposalNotFound(ProposalError):
    pass


class ProposalAlreadyDecided(ProposalError):
    pass


class ProposalStale(ProposalError):
    pass


class ProposalInvalid(ProposalError):
    pass


class ReplacementRequired(ProposalError):
    """Já existe outra leitura para a vaca na data."""

    def __init__(self, existing: OfficialMeasurement) -> None:
        super().__init__(
            "Esta vaca já tem outra produção lançada nesta data. Para substituir, "
            "informe o motivo."
        )
        self.existing = existing


def _fold(value: str | None) -> str:
    decomposed = unicodedata.normalize("NFKD", (value or "").lower())
    return " ".join("".join(c for c in decomposed if not unicodedata.combining(c)).split())


def _as_uuid(value: UUID | str) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


# ------------------------------------------------------------------ criação


async def create_proposals(
    session: AsyncSession,
    *,
    farm_id: UUID | str,
    user: User,
    kind: str,
    label: str,
    extraction: EventExtraction,
    media_asset_id: UUID | None = None,
) -> EventProposalSource:
    """Grava a leitura e uma proposta por evento. Não faz commit."""
    if kind not in SOURCE_KINDS:
        raise ProposalInvalid(f"Origem desconhecida: {kind!r}.")
    farm_id = _as_uuid(farm_id)

    source = EventProposalSource(
        farm_id=farm_id,
        kind=kind,
        label=label[:255],
        extractor_name=extraction.extractor_name[:64],
        extractor_version=extraction.extractor_version[:64],
        reference_date=extraction.reference_date,
        raw_output=extraction.to_raw(),
        created_by_user_id=user.id,
        # A foto vai junto no INSERT: a fonte é imutável, um UPDATE depois
        # seria recusado pelo trigger.
        media_asset_id=media_asset_id,
    )
    session.add(source)
    await session.flush()

    animals = list(
        await session.scalars(
            select(Animal).where(Animal.farm_id == farm_id, Animal.brinco.is_not(None))
        )
    )
    by_brinco = {animal.brinco: animal for animal in animals}

    for position, event in enumerate(extraction.events, start=1):
        payload, alerts = normalize_event(
            event.event_type, event.fields, reference_date=extraction.reference_date
        )
        brinco = normalize_brinco(event.brinco)
        candidate = by_brinco.get(brinco) if brinco else None

        if brinco is None:
            alerts.insert(
                0,
                {
                    "code": "no_brinco",
                    "message": "Brinco não lido. Escolha o animal na revisão"
                    + (f" (nome lido: {event.nome})." if event.nome else "."),
                },
            )
        elif candidate is None:
            variants = brinco_variants(animals, brinco, event.nome)
            if variants:
                listed = ", ".join(f"{a.brinco} · {a.name or '—'}" for a in variants)
                alerts.insert(
                    0,
                    {
                        "code": "brinco_variant",
                        "message": f"Nenhum animal com o brinco {brinco}, mas no cadastro existe "
                        f"{listed}. Confirme se é o mesmo animal.",
                    },
                )
            else:
                alerts.insert(
                    0,
                    {"code": "animal_not_found", "message": f"Nenhum animal com o brinco {brinco}."},
                )
        else:
            # Grafia torta do mesmo nome ("PAETENHA" / PRETINHA) não é
            # divergência; outro nome é — o brinco pode ter sido mal lido.
            if event.nome and name_similarity(event.nome, candidate.name) < SIMILAR_NAME:
                alerts.append(
                    {
                        "code": "name_mismatch",
                        "message": f"Nome lido: {event.nome}; no cadastro: {candidate.name or '—'}. "
                        "A associação é pelo brinco — se o brinco foi lido da linha de "
                        "cima ou de baixo, toque em Trocar animal.",
                    }
                )
            if candidate.exited_on is not None:
                alerts.append(
                    {
                        "code": "animal_exited",
                        "message": f"Animal com baixa em {candidate.exited_on:%d/%m/%Y}.",
                    }
                )

        session.add(
            EventProposal(
                source_id=source.id,
                farm_id=farm_id,
                position=position,
                event_type=event.event_type,
                brinco_lido=(event.brinco or None) and event.brinco[:64],
                nome_lido=(event.nome or None) and event.nome[:255],
                candidate_animal_id=candidate.id if candidate else None,
                raw_fields={"brinco": event.brinco, "nome": event.nome, **event.fields},
                payload=payload,
                evidence=event.evidence,
                confidence=event.confidence,
                alerts=alerts,
            )
        )
    await session.flush()
    return source


# ---------------------------------------------------------------- listagem


_PREFIX = re.compile(r"^B\d+-")


def _brinco_core(brinco: str) -> str:
    """"B2-011" → "11"; "694" → "694". Só para sugerir, nunca para associar."""
    core = _PREFIX.sub("", brinco)
    return core.lstrip("0") or core


def brinco_variants(animals: list[Animal], brinco: str | None, nome: str | None = None) -> list[Animal]:
    """Cadastros cujo brinco difere do lido só por prefixo (B1-, B2-) ou
    zeros à esquerda: "694" ↔ "B2-694", "011" ↔ "B2-11".

    O caderno costuma trazer só o número. Brinco é identidade, então isto é
    só sugestão — quem revisa confirma (decisão do titular, 19/09/2026). O
    nome lido, quando bate, põe o animal na frente.
    """
    if not brinco:
        return []
    wanted = _brinco_core(brinco)
    if not wanted.isdigit():
        return []
    found = [
        a for a in animals
        if a.brinco and a.brinco != brinco and _brinco_core(a.brinco) == wanted
    ]
    folded = _fold(nome)
    return sorted(found, key=lambda a: (_fold(a.name) != folded, a.exited_on is not None, a.brinco))


#: A partir de quanto um nome lido "parece" o do cadastro (0 a 1). Medido na
#: primeira folha real: os nomes mal lidos ficaram entre 0,67 e 0,89 do nome
#: certo ("PAETENHA" → PRETINHA 0,75), e o certo foi sempre o mais parecido.
SIMILAR_NAME = 0.6


def name_similarity(read: str | None, registered: str | None) -> float:
    a, b = _fold(read), _fold(registered)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _one_digit_off(read: str | None, registered: str | None) -> bool:
    """"619" e "B2-649": mesmo tamanho, um dígito diferente — o erro típico
    de leitura de manuscrito (4↔1, 4↔9, 7↔8)."""
    if not read or not registered:
        return False
    a, b = _brinco_core(read), _brinco_core(registered)
    return (
        len(a) == len(b)
        and a.isdigit()
        and b.isdigit()
        and sum(x != y for x, y in zip(a, b, strict=True)) == 1
    )


def name_suggestions(animals: list[Animal], nome: str | None, *, limit: int = 5) -> list[Animal]:
    """Animais cujo nome bate com o lido — igual, contido ou parecido
    ("SASIA" → SABIÁ). Só sugestão: quem revisa escolhe."""
    wanted = _fold(nome)
    if not wanted:
        return []
    exact = [a for a in animals if _fold(a.name) == wanted]
    partial = [a for a in animals if a not in exact and wanted in _fold(a.name)]
    similar = sorted(
        (
            a for a in animals
            if a not in exact and a not in partial and name_similarity(nome, a.name) >= SIMILAR_NAME
        ),
        key=lambda a: -name_similarity(nome, a.name),
    )
    ranked = (
        sorted(exact, key=lambda a: a.exited_on is not None)
        + sorted(partial, key=lambda a: a.exited_on is not None)
        + similar
    )
    return ranked[:limit]


#: Nome só "meio parecido" conta quando o brinco também está a um dígito.
_WEAK_NAME = 0.45


def suggest_animals(
    animals: list[Animal], brinco_lido: str | None, nome_lido: str | None, *, limit: int = 5
) -> list[Animal]:
    """Ordem das sugestões, do sinal mais forte ao mais fraco:

    1. mesmo número com outro prefixo ("694" → B2-694), se o nome lido não o
       desmente;
    2. nomes parecidos — e nome meio parecido com brinco a um dígito
       ("619 NEODA" → B2-649 REDONDA) —, o brinco próximo desempatando;
    3. variantes de prefixo que o nome lido desmente (B2-619 MARIPOZA).
    """
    brinco = normalize_brinco(brinco_lido)
    nome = nome_lido

    def score(animal: Animal) -> float:
        return name_similarity(nome, animal.name) + (0.15 if _one_digit_off(brinco, animal.brinco) else 0)

    pool = name_suggestions(animals, nome, limit=len(animals)) + [
        a for a in animals
        if _one_digit_off(brinco, a.brinco) and name_similarity(nome, a.name) >= _WEAK_NAME
    ]
    by_name = sorted(pool, key=lambda a: (-score(a), a.exited_on is not None))
    variants = brinco_variants(animals, brinco, nome)
    confirmed = [a for a in variants if not nome or name_similarity(nome, a.name) >= SIMILAR_NAME]
    contradicted = [a for a in variants if a not in confirmed]

    ranked: list[Animal] = []
    for animal in confirmed + by_name + contradicted:
        if animal not in ranked:
            ranked.append(animal)
    return ranked[:limit]


def _suggestions_for(
    animals: list[Animal], proposal: EventProposal, candidate: Animal | None
) -> list[Animal]:
    """Sem vaca pelo brinco: as sugestões de sempre. Com vaca pelo brinco mas
    de nome bem diferente do lido: as vacas do nome lido — o brinco pode ter
    vindo da linha vizinha (margem do formulário impresso)."""
    if candidate is None:
        return suggest_animals(animals, proposal.brinco_lido, proposal.nome_lido)
    if proposal.nome_lido and name_similarity(proposal.nome_lido, candidate.name) < SIMILAR_NAME:
        return [a for a in name_suggestions(animals, proposal.nome_lido) if a.id != candidate.id]
    return []


@dataclass
class InboxItem:
    proposal: EventProposal
    source: EventProposalSource
    candidate: Animal | None
    suggestions: list[Animal]
    decided_by: str | None
    #: Quem corrigiu a data do arquivo, quando foi corrigida.
    corrected_by: str | None = None


async def list_proposals(
    session: AsyncSession, *, farm_id: UUID, status: str, limit: int = 100
) -> list[InboxItem]:
    corrector = aliased(User)
    query = (
        select(EventProposal, EventProposalSource, User.email, corrector.email)
        .join(EventProposalSource, EventProposalSource.id == EventProposal.source_id)
        .outerjoin(User, User.id == EventProposal.decided_by_user_id)
        .outerjoin(corrector, corrector.id == EventProposalSource.corrected_by_user_id)
        .where(EventProposal.farm_id == farm_id, EventProposal.status == status)
    )
    if status == STATUS_PENDING:
        query = query.order_by(EventProposalSource.created_at, EventProposal.position)
    else:
        query = query.order_by(EventProposal.decided_at.desc(), EventProposal.position)
    rows = (await session.execute(query.limit(limit))).all()

    animals = list(await session.scalars(select(Animal).where(Animal.farm_id == farm_id)))
    by_id = {animal.id: animal for animal in animals}
    # Ficha juntada a outra nunca é sugerida: a decidida continua mostrando o
    # animal em que foi aplicada, mas a sugestão é sempre a ficha que ficou.
    herd = [animal for animal in animals if animal.merged_into_id is None]
    items = []
    for proposal, source, email, corrected_by in rows:
        animal_id = proposal.applied_animal_id or proposal.candidate_animal_id
        candidate = by_id.get(animal_id) if animal_id else None
        items.append(
            InboxItem(
                proposal=proposal,
                source=source,
                candidate=candidate,
                suggestions=_suggestions_for(herd, proposal, candidate),
                decided_by=email,
                corrected_by=corrected_by,
            )
        )
    return items


async def animal_summary(session: AsyncSession, animal: Animal) -> dict[str, Any]:
    lot = await current_lot(session, animal_id=animal.id, kind=KIND_DIET)
    group = await current_lot(session, animal_id=animal.id, kind=KIND_MANAGEMENT)
    return {
        "id": str(animal.id),
        "brinco": animal.brinco,
        "name": animal.name,
        "situacao": animal.situacao,
        "lote_atual": lot.lote if lot else None,
        "grupo_manejo": group.lote if group else None,
        "exited_on": animal.exited_on.isoformat() if animal.exited_on else None,
    }


# --------------------------------------------------------------- validação


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProductionPayload(_Payload):
    measured_on: date
    producao: float = Field(ge=0, le=MAX_LITERS)


class CalvingPayload(_Payload):
    calved_on: date


class DryOffPayload(_Payload):
    dried_on: date


class ExitPayload(_Payload):
    exited_on: date
    reason: Literal["venda", "morte", "descarte", "doacao", "outro"]
    notes: str | None = Field(default=None, max_length=1000)


class LotChangePayload(_Payload):
    lote: str = Field(min_length=1, max_length=64)
    valid_from: date


class NotePayload(_Payload):
    text: str = Field(min_length=1, max_length=2000)


_PAYLOADS: dict[str, type[_Payload]] = {
    "production": ProductionPayload,
    "calving": CalvingPayload,
    "dry_off": DryOffPayload,
    "exit": ExitPayload,
    "lot_change": LotChangePayload,
    "note": NotePayload,
}

_FIELD_LABEL = {
    "measured_on": "data da coleta",
    "producao": "litros",
    "calved_on": "data do parto",
    "dried_on": "data da secagem",
    "exited_on": "data da baixa",
    "reason": "motivo",
    "notes": "observação",
    "lote": "lote",
    "valid_from": "data da mudança",
    "text": "observação",
}


def validate_payload(event_type: str, payload: dict[str, Any]) -> _Payload:
    """O payload completo e válido, ou :class:`ProposalInvalid` dizendo o campo."""
    model = _PAYLOADS[event_type]
    try:
        validated = model.model_validate(payload)
    except ValidationError as error:
        first = error.errors()[0]
        field = str(first["loc"][0]) if first["loc"] else ""
        label = _FIELD_LABEL.get(field, field)
        if field == "producao" and first["type"] in ("less_than_equal", "greater_than_equal"):
            raise ProposalInvalid(f"Litros fora do plausível (0 a {MAX_LITERS:g}).") from error
        raise ProposalInvalid(f"Preencha {label} corretamente antes de aprovar.") from error

    for name, value in validated.model_dump().items():
        if isinstance(value, date) and value > farm_today():
            raise ProposalInvalid(f"A {_FIELD_LABEL.get(name, name)} não pode ser no futuro.")
    if isinstance(validated, NotePayload) and not validated.text.strip():
        raise ProposalInvalid("Preencha observação corretamente antes de aprovar.")
    return validated


# ----------------------------------------------------------------- decisão


async def _lock_pending(
    session: AsyncSession, *, farm_id: UUID, proposal_id: UUID, expected_version: int
) -> EventProposal:
    proposal = await session.scalar(
        select(EventProposal)
        .where(EventProposal.id == proposal_id, EventProposal.farm_id == farm_id)
        .with_for_update()
    )
    if proposal is None:
        raise ProposalNotFound("Proposta não encontrada.")
    if proposal.status != STATUS_PENDING:
        raise ProposalAlreadyDecided("Esta proposta já foi decidida.")
    if proposal.version != expected_version:
        raise ProposalStale(
            "Esta proposta mudou desde que você a abriu. Atualize a caixa e confira de novo."
        )
    return proposal


def _audit(session, *, farm_id, actor, action, proposal, new) -> None:
    session.add(
        AuditEvent(
            farm_id=farm_id,
            actor=actor,
            action=action,
            entity_type="event_proposal",
            entity_id=proposal.id,
            previous_value={"payload": proposal.payload, "raw_fields": proposal.raw_fields},
            new_value=new,
        )
    )


# ------------------------------------------------------- data do arquivo inteiro

#: Alertas sobre quem é o animal: não dependem da data e sobrevivem à troca.
#: Os primeiros vêm antes dos da leitura, os últimos depois (como na criação).
_IDENTITY_FIRST = frozenset({"no_brinco", "animal_not_found", "brinco_variant"})
_IDENTITY_LAST = frozenset({"name_mismatch", "animal_exited"})


@dataclass
class RedateResult:
    updated: int
    kept_decided: int


async def redate_source(
    session: AsyncSession,
    *,
    farm_id: UUID,
    user: User,
    source_id: UUID,
    new_date: date,
) -> RedateResult:
    """Troca a data de um arquivo lido e recalcula as propostas pendentes.

    Cada proposta é normalizada de novo a partir do que foi lido
    (`raw_fields`, imutável) com a nova data de referência: produção sem data
    própria vai para a nova data, "DEL 45" conta a partir dela, "ontem" também.
    Data escrita na própria linha continua a da linha. Decididas não mudam.
    A fonte guarda a data lida e a corrigida, com quem corrigiu. Não faz commit.
    """
    if new_date > farm_today():
        raise ProposalInvalid(f"A data {new_date:%d/%m/%Y} está no futuro.")
    source = await session.scalar(
        select(EventProposalSource)
        .where(EventProposalSource.id == source_id, EventProposalSource.farm_id == farm_id)
        .with_for_update()
    )
    if source is None:
        raise ProposalNotFound("Arquivo não encontrado.")
    proposals = list(
        await session.scalars(
            select(EventProposal)
            .where(EventProposal.source_id == source.id)
            .order_by(EventProposal.position)
            .with_for_update()
        )
    )

    previous = source.effective_reference_date
    updated = 0
    for proposal in proposals:
        if proposal.status != STATUS_PENDING:
            continue
        fields = {k: v for k, v in proposal.raw_fields.items() if k not in ("brinco", "nome")}
        payload, reading_alerts = normalize_event(
            proposal.event_type, fields, reference_date=new_date
        )
        old = proposal.alerts or []
        proposal.payload = payload
        proposal.alerts = (
            [a for a in old if a.get("code") in _IDENTITY_FIRST]
            + reading_alerts
            + [a for a in old if a.get("code") in _IDENTITY_LAST]
        )
        # Quem estava com o cartão aberto com a data antiga precisa recarregar.
        proposal.version += 1
        updated += 1

    source.corrected_reference_date = new_date
    source.corrected_by_user_id = user.id
    source.corrected_at = datetime.now(timezone.utc)
    session.add(
        AuditEvent(
            farm_id=farm_id,
            actor=user.email,
            action="source_date_corrected",
            entity_type="event_proposal_source",
            entity_id=source.id,
            previous_value={
                "reference_date": previous.isoformat() if previous else None,
                "reference_date_read": source.reference_date.isoformat()
                if source.reference_date
                else None,
            },
            new_value={"reference_date": new_date.isoformat(), "proposals_updated": updated},
        )
    )
    await session.flush()
    return RedateResult(updated=updated, kept_decided=len(proposals) - updated)


async def approve_proposal(
    session: AsyncSession,
    *,
    farm_id: UUID,
    user: User,
    proposal_id: UUID,
    expected_version: int,
    animal_id: UUID,
    payload: dict[str, Any],
    replace_reason: str | None = None,
) -> dict[str, Any]:
    """Aprova e aplica. Devolve o resultado gravado na proposta."""
    proposal = await _lock_pending(
        session, farm_id=farm_id, proposal_id=proposal_id, expected_version=expected_version
    )
    animal = await session.scalar(
        select(Animal).where(Animal.id == animal_id, Animal.farm_id == farm_id)
    )
    if animal is None:
        raise ProposalInvalid("Escolha um animal desta fazenda antes de aprovar.")
    if animal.merged_into_id is not None:
        raise ProposalInvalid("Esta ficha foi juntada a outra: escolha a ficha que ficou.")
    validated = validate_payload(proposal.event_type, payload)
    applied = validated.model_dump(mode="json")
    source = await session.get(EventProposalSource, proposal.source_id)

    def mark(result: dict[str, Any]) -> None:
        proposal.status = STATUS_APPROVED
        proposal.version += 1
        proposal.decided_by_user_id = user.id
        proposal.decided_at = datetime.now(timezone.utc)
        proposal.applied_animal_id = animal.id
        proposal.applied_payload = applied
        proposal.result = result
        _audit(
            session, farm_id=farm_id, actor=user.email, action="proposal_approved",
            proposal=proposal,
            new={"animal_id": str(animal.id), "payload": applied, "result": result},
        )

    def refuse_after_exit(day: date, what: str) -> None:
        if animal.exited_on is not None and day > animal.exited_on:
            raise ProposalInvalid(
                f"O animal teve baixa em {animal.exited_on:%d/%m/%Y}; {what} depois disso "
                "não pode ser registrado."
            )

    event_type = proposal.event_type
    if event_type == "production":
        return await _apply_production(
            session, proposal=proposal, animal=animal, user=user,
            validated=validated, replace_reason=replace_reason, mark=mark,
            refuse_after_exit=refuse_after_exit,
        )

    if event_type == "calving":
        refuse_after_exit(validated.calved_on, "um parto")
        result = {"animal_id": str(animal.id), "ultimo_parto": validated.calved_on.isoformat()}
        mark(result)
        await session.flush()
        await update_animal(
            session, animal_id=animal.id, farm_id=farm_id, actor=user.email,
            changes={"ultimo_parto": validated.calved_on, "situacao": "Em lactação"},
        )
        return result

    if event_type == "dry_off":
        refuse_after_exit(validated.dried_on, "uma secagem")
        result = {"animal_id": str(animal.id), "situacao": "Seca"}
        mark(result)
        await session.flush()
        await update_animal(
            session, animal_id=animal.id, farm_id=farm_id, actor=user.email,
            changes={"situacao": "Seca"},
        )
        return result

    if event_type == "exit":
        result = {"animal_id": str(animal.id), "exited_on": validated.exited_on.isoformat()}
        mark(result)
        await session.flush()
        await register_exit(
            session, animal_id=animal.id, farm_id=farm_id, actor=user.email,
            exited_on=validated.exited_on, reason=validated.reason, notes=validated.notes,
        )
        return result

    if event_type == "lot_change":
        refuse_after_exit(validated.valid_from, "uma mudança de lote")
        result = {"animal_id": str(animal.id), "lote": validated.lote}
        mark(result)
        await session.flush()
        await assign_lot(
            session, animal_id=animal.id, farm_id=farm_id, actor=user.email,
            lote=validated.lote, valid_from=validated.valid_from,
        )
        return result

    # note: vira uma linha datada nas observações do animal. A data é a do
    # arquivo depois da correção de quem revisa, não a que o leitor leu.
    day = (source.effective_reference_date if source else None) or farm_today()
    line = f"{day:%d/%m/%Y}: {validated.text.strip()}"
    observacoes = f"{animal.observacoes}\n{line}" if animal.observacoes else line
    result = {"animal_id": str(animal.id), "observacao": line}
    mark(result)
    await session.flush()
    await update_animal(
        session, animal_id=animal.id, farm_id=farm_id, actor=user.email,
        changes={"observacoes": observacoes},
    )
    return result


async def _apply_production(
    session, *, proposal, animal, user, validated, replace_reason, mark, refuse_after_exit
) -> dict[str, Any]:
    refuse_after_exit(validated.measured_on, "uma produção")
    producao = round(float(validated.producao), 2)
    existing = await session.scalar(
        select(OfficialMeasurement)
        .where(
            OfficialMeasurement.animal_id == animal.id,
            OfficialMeasurement.measured_on == validated.measured_on,
            OfficialMeasurement.status == "active",
        )
        .with_for_update()
    )
    if existing is not None and producao_of(existing) == producao:
        result = {"already_recorded": True, "measurement_id": str(existing.id)}
        mark(result)
        await session.flush()
        return result
    if existing is not None:
        if not replace_reason or len(replace_reason.strip()) < 3:
            raise ReplacementRequired(existing)
        existing.status = "superseded"
        await session.flush()

    # O id da leitura nasce antes: a proposta aprovada já aponta para ela, e
    # depois de aprovada a proposta não pode mais ser alterada.
    measurement_id = uuid.uuid4()
    result = {
        "measurement_id": str(measurement_id),
        "replaced_measurement_id": str(existing.id) if existing is not None else None,
        "replace_reason": replace_reason.strip() if existing is not None else None,
    }
    mark(result)
    await session.flush()
    session.add(
        OfficialMeasurement(
            id=measurement_id,
            animal_id=animal.id,
            measured_on=validated.measured_on,
            values={"producao": producao},
            status="active",
            provenance="proposal_review",
            event_proposal_id=proposal.id,
            reviewed_by=user.email,
            lote_observado=await diet_lot_on(
                session, animal_id=animal.id, day=validated.measured_on
            ),
            supersedes_measurement_id=existing.id if existing is not None else None,
        )
    )
    await session.flush()
    return result


async def reject_proposal(
    session: AsyncSession,
    *,
    farm_id: UUID,
    user: User,
    proposal_id: UUID,
    expected_version: int,
    reason: str,
) -> None:
    """Rejeita com motivo. Não faz commit."""
    proposal = await _lock_pending(
        session, farm_id=farm_id, proposal_id=proposal_id, expected_version=expected_version
    )
    proposal.status = STATUS_REJECTED
    proposal.version += 1
    proposal.decided_by_user_id = user.id
    proposal.decided_at = datetime.now(timezone.utc)
    proposal.decision_reason = reason.strip()
    _audit(
        session, farm_id=farm_id, actor=user.email, action="proposal_rejected",
        proposal=proposal, new={"reason": reason.strip()},
    )
    await session.flush()
