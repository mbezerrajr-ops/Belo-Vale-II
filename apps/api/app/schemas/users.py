"""Contratos HTTP da gestão de contas.

Nenhum modelo de saída inclui `password_hash`: os campos são declarados
explicitamente, em vez de serializar o objeto inteiro, para que um campo novo
e sensível no modelo não vaze por descuido numa resposta.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

Role = Literal["operator", "reviewer", "admin"]


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)
    role: Role


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Role | None = None
    is_active: bool | None = None
    @field_validator("role", "is_active")
    @classmethod
    def no_explicit_null(cls, value):
        if value is None: raise ValueError("Informe um valor válido.")
        return value


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    role: str
    is_active: bool
    #: Senha redefinida e ainda não trocada pelo dono da conta. O nome evita
    #: a palavra "password" de propósito: há um teste que garante que ela
    #: nunca aparece nesta resposta, como proteção contra vazar o hash.
    reset_pending: bool = Field(default=False, validation_alias="must_change_password")
    created_at: datetime


class UserPage(BaseModel):
    items: list[UserRead]
    total: int


class PasswordResetRead(BaseModel):
    """Resposta da redefinição. É o único lugar onde a senha provisória
    aparece: ela não é gravada em texto nem na auditoria."""

    temporary_password: str
    expires_at: datetime
