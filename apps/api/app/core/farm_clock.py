"""Relógio da fazenda.

"Hoje" é o dia no curral, não no servidor: uma API hospedada em UTC viraria o
dia às 21h no Nordeste e aceitaria como "hoje" uma coleta de amanhã. A fazenda
fica em fuso fixo, sem horário de verão desde 2019, então um deslocamento fixo
evita depender da base de fusos do sistema operacional.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from contextvars import ContextVar
from zoneinfo import ZoneInfo

FARM_TZ = timezone(timedelta(hours=-3), name="America/Recife")
farm_timezone: ContextVar[str] = ContextVar("farm_timezone", default="America/Recife")


def farm_today() -> date:
    return datetime.now(ZoneInfo(farm_timezone.get())).date()
