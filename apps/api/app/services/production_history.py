"""Histórico de produção de um animal.

Junta, para cada leitura, o que está espalhado por três lugares:

- a própria medição (data, valor, situação, origem, responsável);
- a importação de arquivo que a criou, quando houver (nome do arquivo e, numa
  substituição, o motivo);
- a trilha de auditoria, que guarda o motivo de correções e anulações.

Nenhuma leitura é omitida: as substituídas e anuladas aparecem marcadas, para
que a ficha conte o que aconteceu, não só o valor de hoje.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditEvent, OfficialMeasurement, ProductionImport
from app.services.production_entry import producao_of

#: Ações de auditoria que carregam o motivo de uma mudança de leitura.
_REASON_ACTIONS = ("measurement_corrected", "measurement_voided")


@dataclass(frozen=True)
class HistoryEntry:
    id: UUID
    measured_on: date
    producao: float | None
    status: str
    provenance: str
    responsible: str | None
    created_at: datetime
    supersedes: UUID | None
    #: Arquivo de origem, para leituras importadas.
    source: str | None
    #: Por que esta leitura mudou algo: correção, anulação ou substituição.
    reason: str | None
    lote_observado: str | None


async def animal_production_history(
    session: AsyncSession, *, animal_id: UUID
) -> list[HistoryEntry]:
    rows = (
        await session.execute(
            select(OfficialMeasurement, ProductionImport.filename, ProductionImport.reason)
            .outerjoin(
                ProductionImport,
                ProductionImport.id == OfficialMeasurement.production_import_id,
            )
            .where(OfficialMeasurement.animal_id == animal_id)
            .order_by(
                OfficialMeasurement.measured_on.desc(),
                OfficialMeasurement.created_at.desc(),
            )
        )
    ).all()
    if not rows:
        return []

    ids = [measurement.id for measurement, _, _ in rows]
    reasons: dict[UUID, str] = {}
    for event in await session.scalars(
        select(AuditEvent).where(
            AuditEvent.entity_type == "measurement",
            AuditEvent.action.in_(_REASON_ACTIONS),
            AuditEvent.entity_id.in_(ids),
        )
    ):
        reason = (event.new_value or {}).get("reason")
        if reason:
            reasons[event.entity_id] = reason

    entries = []
    for measurement, filename, import_reason in rows:
        reason = reasons.get(measurement.id)
        # Numa importação que substituiu, o motivo é o da importação — mas só
        # para as leituras que de fato substituíram outra.
        if reason is None and measurement.supersedes_measurement_id and import_reason:
            reason = import_reason
        entries.append(
            HistoryEntry(
                id=measurement.id,
                measured_on=measurement.measured_on,
                producao=producao_of(measurement),
                status=measurement.status,
                provenance=measurement.provenance,
                responsible=measurement.reviewed_by,
                created_at=measurement.created_at,
                supersedes=measurement.supersedes_measurement_id,
                source=filename,
                reason=reason,
                lote_observado=measurement.lote_observado,
            )
        )
    return entries
