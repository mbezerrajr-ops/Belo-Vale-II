"""Contratos HTTP do lançamento manual de produção."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.production_entry import MAX_LITERS


def _required_reason(value: str) -> str:
    cleaned = value.strip()
    if len(cleaned) < 3:
        raise ValueError("Explique o motivo em poucas palavras.")
    return cleaned


class ReadingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    animal_id: UUID
    measured_on: date
    #: Litros no dia. Zero é válido: leite descartado em tratamento.
    producao: float = Field(ge=0, le=MAX_LITERS)


class CorrectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    producao: float = Field(ge=0, le=MAX_LITERS)
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
    provenance: str
    #: Quem lançou ou aprovou. Para a baseline, quem aprovou a importação.
    entered_by: str | None
    supersedes: UUID | None = None
    created_at: datetime


class SheetItem(BaseModel):
    animal_id: UUID
    brinco: str | None
    name: str | None
    situacao: str | None
    producao: float | None
    measurement_id: UUID | None
    provenance: str | None


class SheetOut(BaseModel):
    measured_on: date
    #: Nulo quando a tela pediu só a lista de lotes.
    lote: str | None
    #: Lotes de ordenha com animais hoje, para o seletor da tela.
    lotes: list[str]
    items: list[SheetItem]
