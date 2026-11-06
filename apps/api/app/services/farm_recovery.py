"""Recuperar uma fazenda de uma cópia isolada sem sobrescrever clientes.

A recuperação sempre cria outra fazenda e outra conta produtora. As chaves
internas são remapeadas; fatos históricos em JSON permanecem como evidência.
"""

from uuid import UUID, uuid4

from app.db.models import Base
from sqlalchemy import func, select

ORDER = [
    "producer_accounts",
    "users",
    "farms",
    "producer_memberships",
    "farm_memberships",
    "animals",
    "baseline_imports",
    "imports",
    "media_assets",
    "extraction_runs",
    "extracted_lines",
    "validation_alerts",
    "review_decisions",
    "production_imports",
    "event_proposal_sources",
    "event_proposals",
    "animal_lot_assignments",
    "supplies",
    "supply_prices",
    "supply_diets",
    "official_measurements",
    "audit_events",
]


async def farm_snapshot(session, farm_id, storage):
    tables = Base.metadata.tables
    farm = (
        (
            await session.execute(
                select(tables["farms"]).where(tables["farms"].c.id == farm_id)
            )
        )
        .mappings()
        .one_or_none()
    )
    if farm is None:
        raise ValueError("Fazenda ausente na cópia de origem.")
    snapshot = {name: [] for name in ORDER}
    snapshot["farms"] = [dict(farm)]
    if farm["producer_account_id"] is None:
        raise ValueError("A origem deve estar migrada para o modelo de produtores.")
    account_id = farm["producer_account_id"]
    for name in ORDER:
        if name in ("users", "farms"):
            continue
        table = tables[name]
        if name == "producer_accounts":
            condition = table.c.id == account_id
        elif name == "producer_memberships":
            condition = table.c.producer_account_id == account_id
        elif "farm_id" in table.c:
            condition = table.c.farm_id == farm_id
        else:
            parent_column, parent = {
                "animal_lot_assignments": ("animal_id", "animals"),
                "official_measurements": ("animal_id", "animals"),
                "supply_prices": ("supply_id", "supplies"),
                "supply_diets": ("supply_id", "supplies"),
                "extraction_runs": ("media_asset_id", "media_assets"),
                "extracted_lines": ("extraction_run_id", "extraction_runs"),
                "validation_alerts": ("extracted_line_id", "extracted_lines"),
                "review_decisions": ("extracted_line_id", "extracted_lines"),
            }[name]
            condition = table.c[parent_column].in_(
                [row["id"] for row in snapshot[parent]]
            )
        snapshot[name] = [
            dict(row)
            for row in (
                await session.execute(select(table).where(condition))
            ).mappings()
        ]
    user_ids = set()
    emails = set()
    for name, rows in snapshot.items():
        table = tables[name]
        user_columns = [
            fk.parent.name
            for fk in table.foreign_keys
            if fk.column.table.name == "users"
        ]
        for row in rows:
            user_ids.update(row[column] for column in user_columns if row.get(column))
            emails.update(
                row[column].lower()
                for column in (
                    "actor",
                    "reviewed_by",
                    "initiated_by",
                    "approved_by",
                    "recorded_by",
                )
                if isinstance(row.get(column), str)
            )
    users = tables["users"]
    snapshot["users"] = [
        dict(row)
        for row in (
            await session.execute(
                select(users).where(
                    users.c.id.in_(user_ids) | func.lower(users.c.email).in_(emails)
                )
            )
        ).mappings()
    ]
    media = {
        row["object_key"]: storage.load(row["object_key"])
        for row in snapshot["media_assets"]
        if row["object_key"]
    }
    return snapshot, media


async def recover_farm(session, snapshot, media, storage, *, apply=False):
    tables = Base.metadata.tables
    report = {
        "tables": {name: len(rows) for name, rows in snapshot.items()},
        "media_files": len(media),
        "applied": False,
    }
    if not apply:
        return report
    ids = {
        row["id"]: uuid4() for rows in snapshot.values() for row in rows if "id" in row
    }
    farm_id = ids[snapshot["farms"][0]["id"]]
    # Identidades atuais prevalecem: uma recuperação nunca troca a senha,
    # estado global ou privilégios de alguém que já usa a plataforma.
    existing_users = set()
    occupied_users = set(
        (
            await session.scalars(
                select(tables["farm_memberships"].c.user_id).where(
                    tables["farm_memberships"].c.is_active
                )
            )
        ).all()
    )
    for row in snapshot["users"]:
        existing = await session.scalar(
            select(tables["users"].c.id).where(
                func.lower(tables["users"].c.email) == row["email"].lower()
            )
        )
        if existing:
            ids[row["id"]] = existing
            existing_users.add(row["id"])
    async with session.begin_nested():
        merged = []
        for name in ORDER:
            rows = list(snapshot[name])
            if name == "official_measurements":
                pending, ordered, complete = rows[:], [], set()
                while pending:
                    ready = [
                        row
                        for row in pending
                        if row["supersedes_measurement_id"] is None
                        or row["supersedes_measurement_id"] in complete
                    ]
                    if not ready:
                        raise ValueError("Histórico de correções incompleto na origem.")
                    for row in ready:
                        pending.remove(row)
                        ordered.append(row)
                        complete.add(row["id"])
                rows = ordered
            for original in rows:
                if name == "users" and original["id"] in existing_users:
                    continue
                row = dict(original)
                for key, value in row.items():
                    if isinstance(value, UUID) and value in ids:
                        row[key] = ids[value]
                if name == "farms":
                    row["code"] = None
                    row["name"] += " (recuperada)"
                if name == "producer_accounts":
                    row["name"] += " (recuperação)"
                if name == "users":
                    row["is_platform_admin"] = False
                if name == "farm_memberships" and row["user_id"] in occupied_users:
                    # A cópia não pode conceder uma segunda fazenda à identidade.
                    row["is_active"] = False
                if name == "animals" and row["merged_into_id"]:
                    merged.append((row["id"], row["merged_into_id"], row["merged_at"]))
                    row["merged_into_id"] = row["merged_at"] = None
                if name == "media_assets" and row["object_key"]:
                    old_key = row["object_key"]
                    new_key = f"{farm_id}/{row['sha256']}"
                    content = media[old_key]
                    from hashlib import sha256

                    if sha256(content).hexdigest() != row["sha256"]:
                        raise ValueError(
                            "A soma de conferência de uma mídia diverge da origem."
                        )
                    storage.save(new_key, content, row["media_type"])
                    row["object_key"] = new_key
                await session.execute(tables[name].insert().values(**row))
        for animal_id, target, when in merged:
            await session.execute(
                tables["animals"]
                .update()
                .where(tables["animals"].c.id == animal_id)
                .values(merged_into_id=target, merged_at=when)
            )
        await session.execute(
            tables["audit_events"]
            .insert()
            .values(
                farm_id=farm_id,
                actor="recuperacao-administrativa",
                action="farm_recovered",
                entity_type="farm",
                entity_id=farm_id,
                previous_value={"source_farm_id": str(snapshot["farms"][0]["id"])},
                new_value={"id_map": {str(old): str(new) for old, new in ids.items()}},
            )
        )
    await session.commit()
    return {**report, "applied": True, "farm_id": str(farm_id)}
