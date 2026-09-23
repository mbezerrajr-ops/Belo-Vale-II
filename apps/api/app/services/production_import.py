"""Importação da coleta de leite: associação, pré-visualização e gravação.

Recebe o que `production_files` leu e decide, linha a linha, o que aconteceria.
A mesma função monta a pré-visualização e a gravação: o que o usuário viu é
exatamente o que será gravado, recalculado no servidor — nunca aceito pronto
do navegador.

Regras decididas pelo titular (2026-09-18):

1. a primeira coluna é o brinco, e **só o brinco associa**; o nome do arquivo
   aparece como aviso quando difere do cadastro, nunca como critério;
2. no modo `replace`, leitura com valor diferente é substituída (a antiga fica
   `superseded`, apontada pela nova); a vaca que já tinha leitura na data e
   **não está no arquivo mantém a leitura antiga**;
3. `new_only` é para qualquer conta; `replace` exige revisor e motivo — a
   checagem de papel fica na rota.
"""

from __future__ import annotations

import hashlib
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.farm_clock import farm_today
from app.db.models import (
    Animal,
    AuditEvent,
    OfficialMeasurement,
    ProductionImport,
    User,
)
from app.services.brinco import normalize_brinco
from app.services.production_entry import (
    MAX_LITERS,
    diet_lot_on,
    merge_reading,
    milkings_of,
    producao_of,
    supersede,
)
from app.services.production_files import FileProblem, ParsedFile

MODE_NEW_ONLY = "new_only"
MODE_REPLACE = "replace"

#: Linhas que viram leitura nova em qualquer modo.
STATUS_NEW = "new"
#: Já existe leitura ativa igual: nada a fazer.
STATUS_SAME = "same"
#: Já existe leitura ativa diferente: `replace` substitui, `new_only` pula.
STATUS_DIFFERENT = "different"
#: Já existe leitura com o mesmo total, e o arquivo traz o que ela não tem
#: (manhã e tarde, a observação): completa em qualquer modo, sem mudar nada.
STATUS_COMPLETE = "complete"
STATUS_NOT_FOUND = "not_found"
STATUS_NO_BRINCO = "no_brinco"
STATUS_INVALID = "invalid"
STATUS_EXITED = "exited"
#: Brinco repetido no arquivo com valores diferentes (todas as ocorrências),
#: ou repetição de uma linha já considerada.
STATUS_DUPLICATE = "duplicate"


class ProductionImportError(ValueError):
    """Importação recusada. A mensagem é para o usuário final."""


class NothingToImport(ProductionImportError):
    pass


def _fold(value: str | None) -> str:
    decomposed = unicodedata.normalize("NFKD", (value or "").upper())
    return " ".join(
        "".join(c for c in decomposed if not unicodedata.combining(c)).split()
    )


@dataclass
class PreviewRow:
    location: str
    brinco_lido: str
    brinco: str | None
    nome_arquivo: str | None
    producao: float
    status: str
    manha: float | None = None
    tarde: float | None = None
    observacao: str | None = None
    animal_id: UUID | None = None
    animal_nome: str | None = None
    existing_measurement_id: UUID | None = None
    existing_producao: float | None = None
    existing_provenance: str | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class KeptReading:
    """Leitura da data que não está no arquivo: fica como está."""

    animal_id: UUID
    brinco: str | None
    nome: str | None
    producao: float | None


@dataclass
class Preview:
    file_format: str
    filename: str
    sha256: str
    measured_on: date
    rows: list[PreviewRow]
    problems: list[FileProblem]
    kept: list[KeptReading]

    def counts(self) -> dict[str, int]:
        counted = Counter(row.status for row in self.rows)
        return {status: counted.get(status, 0) for status in (
            STATUS_NEW,
            STATUS_SAME,
            STATUS_COMPLETE,
            STATUS_DIFFERENT,
            STATUS_NOT_FOUND,
            STATUS_NO_BRINCO,
            STATUS_INVALID,
            STATUS_EXITED,
            STATUS_DUPLICATE,
        )}


def _values(row: PreviewRow) -> dict[str, float]:
    milkings = {key: value for key, value in (("manha", row.manha), ("tarde", row.tarde)) if value is not None}
    return {"producao": row.producao, **milkings}


def sha256_of(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _mark_duplicates(rows: list[PreviewRow]) -> None:
    """Brinco repetido no arquivo.

    Mesmo valor: a primeira ocorrência vale e as outras são ignoradas. Valores
    diferentes: nenhuma vale — escolher uma seria adivinhar qual está certa.
    """
    by_brinco: dict[str, list[PreviewRow]] = {}
    for row in rows:
        if row.brinco is not None and row.status not in (STATUS_INVALID, STATUS_NO_BRINCO):
            by_brinco.setdefault(row.brinco, []).append(row)
    for brinco, group in by_brinco.items():
        if len(group) < 2:
            continue
        values = {(row.producao, row.manha, row.tarde) for row in group}
        if len(values) > 1:
            for row in group:
                row.status = STATUS_DUPLICATE
                row.notes.append(
                    f"Brinco {brinco} aparece {len(group)} vezes com valores diferentes; "
                    "nenhuma linha foi considerada."
                )
        else:
            for row in group[1:]:
                row.status = STATUS_DUPLICATE
                row.notes.append(f"Repetição de {group[0].location}, com o mesmo valor.")


async def build_preview(
    session: AsyncSession,
    *,
    farm_id: UUID,
    parsed: ParsedFile,
    content: bytes,
    filename: str,
    measured_on: date,
    lock: bool = False,
) -> Preview:
    """O que a importação faria. Não grava nada.

    `lock=True` trava as leituras da data encontradas, para a gravação que
    vem em seguida na mesma transação não disputar com outra importação.
    """
    if measured_on > farm_today():
        raise ProductionImportError("A data da coleta não pode ser no futuro.")

    animals = list(
        await session.scalars(
            select(Animal).where(Animal.farm_id == farm_id, Animal.brinco.is_not(None))
        )
    )
    by_brinco = {animal.brinco: animal for animal in animals}

    readings_query = (
        select(OfficialMeasurement)
        .join(Animal, Animal.id == OfficialMeasurement.animal_id)
        .where(
            Animal.farm_id == farm_id,
            OfficialMeasurement.measured_on == measured_on,
            OfficialMeasurement.status == "active",
        )
    )
    if lock:
        readings_query = readings_query.with_for_update(of=OfficialMeasurement)
    active = {m.animal_id: m for m in await session.scalars(readings_query)}

    rows: list[PreviewRow] = []
    for parsed_row in parsed.rows:
        brinco = normalize_brinco(parsed_row.brinco_raw)
        row = PreviewRow(
            location=parsed_row.location,
            brinco_lido=parsed_row.brinco_raw,
            brinco=brinco,
            nome_arquivo=parsed_row.nome,
            producao=round(parsed_row.producao, 2),
            status=STATUS_NEW,
            manha=parsed_row.manha,
            tarde=parsed_row.tarde,
            observacao=parsed_row.observacao,
        )
        rows.append(row)

        if brinco is None:
            row.status = STATUS_NO_BRINCO
            continue
        if not 0 <= row.producao <= MAX_LITERS:
            row.status = STATUS_INVALID
            row.notes.append(f"Produção fora do plausível (0 a {MAX_LITERS:g} L).")
            continue

        animal = by_brinco.get(brinco)
        if animal is None:
            row.status = STATUS_NOT_FOUND
            if parsed_row.brinco_from_number and brinco.isdigit():
                padded = [
                    b for b in by_brinco if b.isdigit() and b != brinco and b.lstrip("0") == brinco
                ]
                if padded:
                    row.notes.append(
                        f"A planilha guardou o brinco como número e pode ter apagado o "
                        f"zero à esquerda (existe o brinco {', '.join(sorted(padded))}). "
                        "Formate a coluna como texto e envie de novo."
                    )
            continue

        row.animal_id = animal.id
        row.animal_nome = animal.name
        if row.nome_arquivo and _fold(row.nome_arquivo) != _fold(animal.name):
            row.notes.append(
                f"Nome no arquivo: {row.nome_arquivo}; no cadastro: {animal.name or '—'}. "
                "A associação é pelo brinco."
            )
        if animal.exited_on is not None and measured_on > animal.exited_on:
            row.status = STATUS_EXITED
            row.notes.append(f"Animal com baixa em {animal.exited_on:%d/%m/%Y}.")
            continue

        existing = active.get(animal.id)
        if existing is not None:
            row.existing_measurement_id = existing.id
            row.existing_producao = producao_of(existing)
            row.existing_provenance = existing.provenance
            merged = merge_reading(existing, _values(row), row.observacao)
            if merged is None:
                row.status = STATUS_DIFFERENT
            elif merged == (
                {"producao": producao_of(existing), **milkings_of(existing)},
                existing.observacao,
            ):
                row.status = STATUS_SAME
            else:
                row.status = STATUS_COMPLETE

    _mark_duplicates(rows)

    in_file = {row.animal_id for row in rows if row.animal_id is not None}
    animal_by_id = {animal.id: animal for animal in animals}
    kept = []
    for animal_id, measurement in active.items():
        if animal_id in in_file:
            continue
        animal = animal_by_id.get(animal_id)
        kept.append(
            KeptReading(
                animal_id=animal_id,
                brinco=animal.brinco if animal else None,
                nome=animal.name if animal else None,
                producao=producao_of(measurement),
            )
        )
    kept.sort(key=lambda k: (k.brinco or "", k.nome or ""))

    return Preview(
        file_format=parsed.file_format,
        filename=filename,
        sha256=sha256_of(content),
        measured_on=measured_on,
        rows=rows,
        problems=parsed.problems,
        kept=kept,
    )


@dataclass
class CommitResult:
    production_import: ProductionImport
    already_imported: bool


async def find_same_import(
    session: AsyncSession, *, farm_id: UUID, measured_on: date, sha256: str, mode: str
) -> ProductionImport | None:
    return await session.scalar(
        select(ProductionImport).where(
            ProductionImport.farm_id == farm_id,
            ProductionImport.measured_on == measured_on,
            ProductionImport.sha256 == sha256,
            ProductionImport.mode == mode,
        )
    )


async def commit_import(
    session: AsyncSession,
    *,
    farm_id: UUID,
    user: User,
    parsed: ParsedFile,
    content: bytes,
    filename: str,
    measured_on: date,
    mode: str,
    reason: str | None,
) -> CommitResult:
    """Grava a importação numa transação. Não faz commit."""
    if mode not in (MODE_NEW_ONLY, MODE_REPLACE):
        raise ProductionImportError("Modo de importação desconhecido.")
    if mode == MODE_REPLACE and (reason is None or len(reason.strip()) < 3):
        raise ProductionImportError(
            "Substituir a coleta de uma data exige o motivo, em poucas palavras."
        )

    sha256 = sha256_of(content)
    previous = await find_same_import(
        session, farm_id=farm_id, measured_on=measured_on, sha256=sha256, mode=mode
    )
    if previous is not None:
        return CommitResult(production_import=previous, already_imported=True)

    preview = await build_preview(
        session,
        farm_id=farm_id,
        parsed=parsed,
        content=content,
        filename=filename,
        measured_on=measured_on,
        lock=True,
    )
    to_create = [row for row in preview.rows if row.status == STATUS_NEW]
    to_replace = (
        [row for row in preview.rows if row.status == STATUS_DIFFERENT]
        if mode == MODE_REPLACE
        else []
    )
    to_complete = [row for row in preview.rows if row.status == STATUS_COMPLETE]
    if not to_create and not to_replace and not to_complete:
        raise NothingToImport(
            "Nada a importar: todas as leituras válidas do arquivo já estão lançadas"
            + (" (as diferentes só entram no modo substituir)." if mode == MODE_NEW_ONLY else ".")
        )

    counts = preview.counts()
    summary = {
        "created": len(to_create),
        "replaced": len(to_replace),
        "completed": len(to_complete),
        "skipped_same": counts[STATUS_SAME],
        "skipped_different": counts[STATUS_DIFFERENT] - len(to_replace),
        "not_found": counts[STATUS_NOT_FOUND],
        "no_brinco": counts[STATUS_NO_BRINCO],
        "invalid": counts[STATUS_INVALID],
        "exited": counts[STATUS_EXITED],
        "duplicate": counts[STATUS_DUPLICATE],
        "unreadable_lines": len(preview.problems),
        "kept": len(preview.kept),
    }

    record = ProductionImport(
        farm_id=farm_id,
        measured_on=measured_on,
        filename=filename,
        file_format=preview.file_format,
        sha256=sha256,
        byte_size=len(content),
        content=content,
        mode=mode,
        reason=reason.strip() if reason else None,
        imported_by_user_id=user.id,
        summary=summary,
    )
    session.add(record)
    await session.flush()

    # A antiga deixa de ser ativa antes da nova entrar: o índice único
    # parcial admite uma leitura ativa por vaca e data.
    superseded: dict[UUID, UUID] = {}
    for row in to_replace:
        old = await session.get(OfficialMeasurement, row.existing_measurement_id)
        old.status = "superseded"
        superseded[row.animal_id] = old.id
    if superseded:
        await session.flush()

    for row in [*to_create, *to_replace]:
        session.add(
            OfficialMeasurement(
                animal_id=row.animal_id,
                measured_on=measured_on,
                values=_values(row),
                observacao=row.observacao,
                status="active",
                provenance="file_import",
                production_import_id=record.id,
                reviewed_by=user.email,
                lote_observado=await diet_lot_on(
                    session, animal_id=row.animal_id, day=measured_on
                ),
                supersedes_measurement_id=superseded.get(row.animal_id),
            )
        )
    await session.flush()

    # Completar não muda o que estava lançado: nova versão com o que faltava.
    for row in to_complete:
        old = await session.get(OfficialMeasurement, row.existing_measurement_id)
        merged_values, merged_note = merge_reading(old, _values(row), row.observacao)
        await supersede(
            session,
            farm_id=farm_id,
            user=user,
            previous=old,
            values=merged_values,
            observacao=merged_note,
            action="measurement_completed",
            reason=f"Completada pela importação de {filename}",
            production_import_id=record.id,
        )

    # O arquivo fica no registro de importação; a auditoria guarda o resumo.
    session.add(
        AuditEvent(
            farm_id=farm_id,
            actor=user.email,
            action="production_imported",
            entity_type="production_import",
            entity_id=record.id,
            new_value={
                **summary,
                "measured_on": measured_on.isoformat(),
                "filename": filename,
                "sha256": sha256,
                "mode": mode,
                "reason": record.reason,
            },
        )
    )
    return CommitResult(production_import=record, already_imported=False)


def preview_as_dict(preview: Preview) -> dict:
    return {
        "file_format": preview.file_format,
        "filename": preview.filename,
        "sha256": preview.sha256,
        "measured_on": preview.measured_on,
        "counts": preview.counts(),
        "rows": [asdict(row) for row in preview.rows],
        "problems": [asdict(problem) for problem in preview.problems],
        "kept": [asdict(k) for k in preview.kept],
    }
