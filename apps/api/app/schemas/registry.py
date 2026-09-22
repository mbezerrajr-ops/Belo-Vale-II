"""Contratos HTTP do cadastro mestre.

Nenhum payload aceita `farm_id`: a fazenda é resolvida no servidor, conforme a
decisão de operação monofazenda. Campos extras enviados pelo cliente são
ignorados em vez de aceitos silenciosamente como identidade.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FarmCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    code: str | None = Field(default=None, max_length=64)


class FarmRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    code: str | None = None


class AnimalCreate(BaseModel):
    #: Nulo é válido: um animal pode ser cadastrado antes de ganhar brinco.
    brinco: str | None = Field(default=None, max_length=64)
    name: str | None = Field(default=None, max_length=255)
    numero_legado: str | None = Field(default=None, max_length=64)
    situacao: str | None = Field(default=None, max_length=32)
    status: str | None = Field(default=None, max_length=32)
    ultimo_parto: date | None = None
    nascimento: date | None = None
    peso: float | None = Field(default=None, ge=0)
    observacoes: str | None = None
    lote: str | None = Field(default=None, max_length=64)
    lote_valid_from: date | None = None


class AnimalUpdate(BaseModel):
    """Só campos descritivos. Brinco e lote têm endpoints próprios, porque
    mudam identidade e histórico."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=255)
    numero_legado: str | None = Field(default=None, max_length=64)
    situacao: str | None = Field(default=None, max_length=32)
    status: str | None = Field(default=None, max_length=32)
    ultimo_parto: date | None = None
    nascimento: date | None = None
    peso: float | None = Field(default=None, ge=0)
    observacoes: str | None = None


class BrincoLink(BaseModel):
    brinco: str = Field(min_length=1, max_length=64)
    evidence: str = Field(
        min_length=1,
        description=(
            "Justificativa da vinculação. Muda a identidade operacional do "
            "animal, então fica registrada na auditoria."
        ),
    )


class BrincoUnlink(BaseModel):
    evidence: str = Field(
        min_length=1,
        description=(
            "Justificativa de tirar o brinco (caiu da orelha, estava na vaca "
            "errada). Muda a identidade operacional, então fica na auditoria."
        ),
    )


class LotAssign(BaseModel):
    lote: str = Field(min_length=1, max_length=64)
    valid_from: date
    #: Omitido, é deduzido do nome: "LOTE 2" é ordenha, o resto é manejo.
    kind: Literal["diet", "management"] | None = None


class LotAssignmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    lote: str
    #: `diet` = lote de ordenha; `management` = área ou categoria da fazenda.
    kind: str
    valid_from: date
    valid_to: date | None
    source: str
    reviewed_by: str | None


class AnimalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    farm_id: UUID
    brinco: str | None
    brinco_origem: str | None
    legacy_id: str | None
    numero_legado: str | None
    name: str | None
    situacao: str | None
    status: str | None
    ultimo_parto: date | None
    nascimento: date | None
    peso: float | None
    observacoes: str | None
    #: Lote de ordenha vigente. Nulo quando o animal não está em nenhum.
    lote_atual: str | None = None
    #: Área ou categoria em que o animal está (BEZERREIRO, ENGORDA…).
    grupo_manejo: str | None = None
    #: Baixa. Nulos enquanto o animal está no rebanho.
    exited_on: date | None = None
    exit_reason: str | None = None
    exit_notes: str | None = None
    #: Ficha duplicada juntada a outra: aponta para a que ficou.
    merged_into_id: UUID | None = None
    merged_at: datetime | None = None


class MergedFicha(BaseModel):
    """Uma ficha duplicada que foi juntada a esta."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str | None
    numero_legado: str | None
    merged_at: datetime | None


class AnimalDetail(AnimalRead):
    historico_lotes: list[LotAssignmentRead] = []
    fichas_juntadas: list[MergedFicha] = []


class MergeIn(BaseModel):
    other_id: UUID
    reason: str = Field(max_length=500)

    @field_validator("reason")
    @classmethod
    def _required(cls, value: str) -> str:
        if len(value.strip()) < 3:
            raise ValueError("Diga em poucas palavras por que as fichas são do mesmo animal.")
        return value.strip()


class MergeMove(BaseModel):
    measured_on: date
    producao: float | None


class MergeConflict(BaseModel):
    measured_on: date
    keep: float | None
    drop: float | None


class MergePreview(BaseModel):
    """O que a junção faria, antes de fazer."""

    keep: AnimalRead
    drop: AnimalRead
    moves: list[MergeMove]
    conflicts: list[MergeConflict]
    fills: dict[str, Any]
    lots: list[str]
    pending_proposals: int
    blockers: list[str]


class AnimalPage(BaseModel):
    items: list[AnimalRead]
    total: int
    limit: int
    offset: int


ExitReason = Literal["venda", "morte", "descarte", "doacao", "outro"]


class AnimalExit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exited_on: date
    reason: ExitReason
    notes: str | None = Field(default=None, max_length=1000)


class AnimalExitUndo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(max_length=500)

    @field_validator("reason")
    @classmethod
    def _required(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 3:
            raise ValueError("Explique em poucas palavras por que desfazer a baixa.")
        return cleaned
