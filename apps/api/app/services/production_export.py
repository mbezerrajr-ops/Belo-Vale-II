"""Exportação da produção de um período para planilha (XLSX).

Uma linha por vaca por dia, com o que está valendo: só leituras ativas — as
substituídas e as anuladas continuam no histórico do sistema, mas não na
planilha, que é para conferir e trabalhar os números, não para auditoria.

O lote é o de ordenha em que a vaca estava no dia: o que a leitura gravou ao
ser lançada (`lote_observado`) ou, nas leituras da base antiga, que não o
gravavam, o da lotação vigente naquela data.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from openpyxl import Workbook
from openpyxl.styles import Font
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Animal, AnimalLotAssignment, OfficialMeasurement
from app.services.lot_kind import KIND_DIET
from app.services.production_entry import milkings_of, producao_of

#: Um ano por planilha: o bastante para fechar uma safra, e um teto para o
#: arquivo não crescer sem limite num pedido só.
MAX_DAYS = 366

COLUMNS = ("Data", "Lote", "Brinco", "Nome", "Manhã (L)", "Tarde (L)", "Total (L)", "Observação")
WIDTHS = (12, 12, 10, 24, 11, 11, 11, 40)

MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@dataclass(frozen=True)
class ExportRow:
    measured_on: date
    lote: str | None
    brinco: str | None
    nome: str | None
    manha: float | None
    tarde: float | None
    total: float | None
    observacao: str | None


async def export_rows(
    session: AsyncSession, *, farm_id: UUID, start: date, end: date
) -> list[ExportRow]:
    """As leituras ativas do período, em ordem de data, lote e brinco."""
    readings = (
        await session.execute(
            select(OfficialMeasurement, Animal)
            .join(Animal, Animal.id == OfficialMeasurement.animal_id)
            .where(
                Animal.farm_id == farm_id,
                OfficialMeasurement.status == "active",
                OfficialMeasurement.measured_on >= start,
                OfficialMeasurement.measured_on <= end,
            )
        )
    ).all()

    # Lotação de ordenha de todas as vacas, numa consulta só, para as leituras
    # antigas que não guardaram o lote.
    lots: dict[UUID, list[tuple[date, date | None, str]]] = {}
    for animal_id, lote, valid_from, valid_to in await session.execute(
        select(
            AnimalLotAssignment.animal_id,
            AnimalLotAssignment.lote,
            AnimalLotAssignment.valid_from,
            AnimalLotAssignment.valid_to,
        )
        .join(Animal, Animal.id == AnimalLotAssignment.animal_id)
        .where(Animal.farm_id == farm_id, AnimalLotAssignment.kind == KIND_DIET)
        .order_by(AnimalLotAssignment.valid_from)
    ):
        lots.setdefault(animal_id, []).append((valid_from, valid_to, lote))

    def lot_on(animal_id: UUID, day: date) -> str | None:
        # Mesma regra de `diet_lot_on`: o fim da lotação conta como dentro dela.
        for valid_from, valid_to, lote in lots.get(animal_id, []):
            if valid_from <= day and (valid_to is None or valid_to >= day):
                return lote
        return None

    rows = []
    for measurement, animal in readings:
        milkings = milkings_of(measurement)
        rows.append(
            ExportRow(
                measured_on=measurement.measured_on,
                lote=measurement.lote_observado or lot_on(animal.id, measurement.measured_on),
                brinco=animal.brinco,
                nome=animal.name,
                manha=milkings.get("manha"),
                tarde=milkings.get("tarde"),
                total=producao_of(measurement),
                observacao=measurement.observacao,
            )
        )
    rows.sort(key=lambda r: (r.measured_on, r.lote or "~", r.brinco or "~", r.nome or ""))
    return rows


def _text(cell, value: str | None) -> None:
    """Texto sempre como texto: um nome que comece com "=" não vira fórmula."""
    if value is None:
        return
    cell.value = value
    cell.data_type = "s"


def build_workbook(rows: list[ExportRow], *, start: date, end: date) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Produção"
    workbook.properties.title = f"Produção de {start:%d/%m/%Y} a {end:%d/%m/%Y}"

    sheet.append(COLUMNS)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for column, width in zip("ABCDEFGH", WIDTHS):
        sheet.column_dimensions[column].width = width

    for number, row in enumerate(rows, start=2):
        sheet.cell(number, 1, row.measured_on).number_format = "dd/mm/yyyy"
        _text(sheet.cell(number, 2), row.lote)
        # O brinco é texto: "016" e "16" são brincos diferentes.
        _text(sheet.cell(number, 3), row.brinco)
        _text(sheet.cell(number, 4), row.nome)
        for column, liters in ((5, row.manha), (6, row.tarde), (7, row.total)):
            if liters is not None:
                sheet.cell(number, column, liters).number_format = "0.0"
        _text(sheet.cell(number, 8), row.observacao)

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:H{max(len(rows) + 1, 1)}"

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
