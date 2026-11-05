import re
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator


class EmailInput(BaseModel):
    email: str = Field(min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Informe um e-mail válido.")
        return value


class Registration(EmailInput):
    password: str = Field(min_length=1, max_length=1024)
    producer_name: str = Field(min_length=1, max_length=255)
    farm_name: str = Field(min_length=1, max_length=255)

    @field_validator("producer_name", "farm_name")
    @classmethod
    def clean_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Informe um nome.")
        return value


class ProducerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class TokenInput(BaseModel):
    token: str = Field(min_length=20, max_length=256)


class RecoverPassword(TokenInput):
    password: str = Field(min_length=1, max_length=1024)


class LotSetting(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    kind: Literal["diet", "management"]

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        value = " ".join(value.split())
        if not value:
            raise ValueError("Informe o nome do lote.")
        return value


class FarmSettings(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    timezone: str = "America/Recife"
    lot_settings: list[LotSetting] = Field(default_factory=list, max_length=100)
    milk_price_per_liter: float | None = Field(default=None, ge=0, le=1000)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Fuso horário inválido.")
        return value

    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Informe o nome da fazenda.")
        return value

    @field_validator("lot_settings")
    @classmethod
    def unique_lots(cls, values):
        if len({v.name.casefold() for v in values}) != len(values):
            raise ValueError("Os nomes dos lotes não podem se repetir.")
        return values


class NewFarm(FarmSettings):
    producer_account_id: UUID


class Invitation(EmailInput):
    role: Literal["operator", "reviewer", "admin"]


class MembershipUpdate(BaseModel):
    role: Literal["operator", "reviewer", "admin"]
    is_active: bool = True


class TransferOwnership(BaseModel):
    user_id: UUID
    current_password: str
