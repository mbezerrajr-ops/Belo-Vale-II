"""Contratos HTTP do lançamento manual de produção."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.production_entry import MAX_LITERS


def _required_reason(value: str) -> str:
    cleaned = value.strip()
    if len(cleaned) < 3:
        raise ValueError("Explique o motivo em poucas palavras.")
    return cleaned


Liters = Annotated[float, Field(ge=0, le=MAX_LITERS)]


class _Liters(BaseModel):
    """Total do dia, ou manhã e tarde (o total é a soma). Zero é válido:
    leite descartado em tratamento."""

    producao: Liters | None = None
    manha: Liters | None = None
    tarde: Liters | None = None
    #: Anotação da pesagem para a vaca ("→ Seca", "→ 3º Lote").
    observacao: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _some_liters(self) -> _Liters:
        if self.producao is None and self.manha is None and self.tarde is None:
            raise ValueError("Informe os litros: manhã, tarde ou o total do dia.")
        return self


class ReadingIn(_Liters):
    model_config = ConfigDict(extra="forbid")

    animal_id: UUID
    measured_on: date


class CorrectionIn(_Liters):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(max_length=500)

    _reason = field_validator("reason")(_required_reason)


class VoidIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(max_length=500)

    _reason = field_validator("reason")(_required_reason)


class ReadingOut(BaseModel):
    id: UUID
    animal_id: UUID
    measured_on: date
    producao: float | None
    manha: float | None = None
    tarde: float | None = None
    observacao: str | None = None
    provenance: str
    #: Quem lançou ou aprovou. Para a baseline, quem aprovou a importação.
    entered_by: str | None
    supersedes: UUID | None = None
    created_at: datetime


class PreviousReading(BaseModel):
    measured_on: date
    producao: float | None


class SheetItem(BaseModel):
    animal_id: UUID
    brinco: str | None
    name: str | None
    situacao: str | None
    producao: float | None
    manha: float | None = None
    tarde: float | None = None
    observacao: str | None = None
    measurement_id: UUID | None
    provenance: str | None
    #: A pesagem anterior da vaca, para a folha em branco.
    anterior: PreviousReading | None = None


class SheetOut(BaseModel):
    measured_on: date
    #: Nulo quando a tela pediu só a lista de lotes.
    lote: str | None
    #: Lotes de ordenha com animais hoje, para o seletor da tela.
    lotes: list[str]
    items: list[SheetItem]
