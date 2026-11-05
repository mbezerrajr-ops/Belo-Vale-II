"""Entrada de cadastro próprio por CSV, com prévia e aplicação atômica."""

import csv
import io
from typing import Annotated

from app.core.security import require_minimum_role
from app.core.tenancy import FarmAccess
from app.db.models import Animal
from app.db.session import get_db_session
from app.services.animal_registry import create_animal
from app.services.brinco import normalize_brinco
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/animals/import", tags=["registry"])
ReviewerAccess = Annotated[FarmAccess, Depends(require_minimum_role("reviewer"))]


class CatalogueInput(BaseModel):
    csv: str = Field(min_length=1, max_length=5_000_000)


async def preview(session, farm, content):
    try:
        dialect = csv.Sniffer().sniff(content[:4096], delimiters=";,\t")
        reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")), dialect=dialect)
        if not reader.fieldnames or not {"brinco", "nome"}.issubset(
            {name.strip().lower() for name in reader.fieldnames}
        ):
            raise ValueError(
                "O CSV precisa das colunas brinco e nome; lote é opcional."
            )
        rows = []
        known = set(
            await session.scalars(
                select(Animal.brinco).where(
                    Animal.farm_id == farm.id, Animal.brinco.is_not(None)
                )
            )
        )
        lots = {item["name"].casefold() for item in farm.lot_settings}
        seen = set()
        for index, source in enumerate(reader, start=2):
            if index > 5001:
                raise ValueError("O limite é de 5000 animais por arquivo.")
            source = {
                str(key).strip().lower(): str(value or "").strip()
                for key, value in source.items()
            }
            brinco = normalize_brinco(source.get("brinco"))
            name = source.get("nome", "")
            lot = source.get("lote") or None
            status = "new"
            reason = None
            if not brinco or not name or len(brinco) > 64 or len(name) > 255:
                status, reason = (
                    "invalid",
                    "Informe brinco legível e nome, dentro dos limites.",
                )
            elif brinco in known:
                status, reason = "existing", "Brinco já cadastrado nesta fazenda."
            elif brinco in seen:
                status, reason = "invalid", "Brinco repetido no arquivo."
            elif lot and lot.casefold() not in lots:
                status, reason = (
                    "invalid",
                    "Configure este lote na fazenda antes de importar.",
                )
            seen.add(brinco)
            rows.append(
                {
                    "line": index,
                    "brinco": brinco,
                    "name": name,
                    "lote": lot,
                    "status": status,
                    "reason": reason,
                }
            )
        return {
            "items": rows,
            "new": sum(row["status"] == "new" for row in rows),
            "invalid": sum(row["status"] == "invalid" for row in rows),
        }
    except (csv.Error, ValueError) as error:
        raise HTTPException(422, str(error)) from error


@router.post("/preview")
async def preview_catalogue(
    payload: CatalogueInput,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    access: ReviewerAccess,
):
    return await preview(session, access.farm, payload.csv)


@router.post("", status_code=201)
async def import_catalogue(
    payload: CatalogueInput,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    access: ReviewerAccess,
):
    report = await preview(session, access.farm, payload.csv)
    if report["invalid"]:
        raise HTTPException(422, "Corrija as linhas inválidas antes de importar.")
    for row in report["items"]:
        if row["status"] == "new":
            await create_animal(
                session,
                farm_id=access.farm.id,
                actor=access.email,
                brinco=row["brinco"],
                name=row["name"],
                lote=row["lote"],
                status="Ativo",
                commit=False,
            )
    await session.commit()
    return {
        "created": report["new"],
        "message": f"{report['new']} animais cadastrados. Os registros existentes foram preservados.",
    }
