"""Separate animal identity (brinco/legacy_id), add lot history and honest
baseline provenance for official measurements.

Aditiva: nenhuma coluna existente é removida ou renomeada, e ``identifier``
permanece para não quebrar o pipeline de ingestão atual.

Revision ID: 0004_identity_and_lot_history
Revises: 0003_review_versioning
Create Date: 2026-09-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0004_identity_and_lot_history"
down_revision = "0003_review_versioning"
branch_labels = None
depends_on = None


_OLD_PROVENANCE_CHECK = (
    "status <> 'active' OR (review_decision_id IS NOT NULL "
    "AND reviewed_by IS NOT NULL AND length(btrim(reviewed_by)) > 0)"
)

_NEW_PROVENANCE_CHECK = (
    "status <> 'active' OR ("
    " (provenance = 'ocr_review'"
    "  AND review_decision_id IS NOT NULL"
    "  AND reviewed_by IS NOT NULL AND length(btrim(reviewed_by)) > 0)"
    " OR"
    " (provenance = 'legacy_baseline'"
    "  AND baseline_import_id IS NOT NULL"
    "  AND reviewed_by IS NOT NULL AND length(btrim(reviewed_by)) > 0)"
    ")"
)

#: Versão de 0001: exigia ReviewDecision aprovada para qualquer medição ativa.
_ENSURE_APPROVAL_FUNCTION_V1 = """
CREATE OR REPLACE FUNCTION ensure_active_measurement_approval() RETURNS trigger AS $$
BEGIN
    IF NEW.status = 'active' AND NOT EXISTS (
        SELECT 1
        FROM review_decisions
        WHERE id = NEW.review_decision_id
          AND decision = 'approved'
          AND actor = NEW.reviewed_by
    ) THEN
        RAISE EXCEPTION 'active measurements require an approved review decision and matching actor';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

#: Reconhece a origem declarada, com rigor equivalente nos dois caminhos.
_ENSURE_APPROVAL_FUNCTION_V2 = """
CREATE OR REPLACE FUNCTION ensure_active_measurement_approval() RETURNS trigger AS $$
BEGIN
    IF NEW.status = 'active' THEN
        IF NEW.provenance = 'ocr_review' THEN
            IF NOT EXISTS (
                SELECT 1
                FROM review_decisions
                WHERE id = NEW.review_decision_id
                  AND decision = 'approved'
                  AND actor = NEW.reviewed_by
            ) THEN
                RAISE EXCEPTION 'active measurements require an approved review decision and matching actor';
            END IF;
        ELSIF NEW.provenance = 'legacy_baseline' THEN
            IF NOT EXISTS (
                SELECT 1
                FROM baseline_imports
                WHERE id = NEW.baseline_import_id
                  AND approved_by = NEW.reviewed_by
            ) THEN
                RAISE EXCEPTION 'active baseline measurements require an approved baseline import and matching approver';
            END IF;
        ELSE
            RAISE EXCEPTION 'unknown measurement provenance: %', NEW.provenance;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    # --- animals: identidade separada e campos do cadastro legado ---
    for column in (
        sa.Column("brinco", sa.String(length=64), nullable=True),
        sa.Column("brinco_origem", sa.String(length=64), nullable=True),
        sa.Column("legacy_id", sa.String(length=64), nullable=True),
        sa.Column("numero_legado", sa.String(length=64), nullable=True),
        sa.Column("situacao", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("ultimo_parto", sa.Date(), nullable=True),
        sa.Column("nascimento", sa.Date(), nullable=True),
        sa.Column("peso", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("observacoes", sa.Text(), nullable=True),
    ):
        op.add_column("animals", column)

    # Índices parciais: múltiplos nulos são permitidos, porque não ter brinco
    # é um estado válido (142 registros da baseline).
    op.create_index(
        "uq_animals_farm_brinco",
        "animals",
        ["farm_id", "brinco"],
        unique=True,
        postgresql_where=sa.text("brinco IS NOT NULL"),
    )
    op.create_index(
        "uq_animals_farm_legacy_id",
        "animals",
        ["farm_id", "legacy_id"],
        unique=True,
        postgresql_where=sa.text("legacy_id IS NOT NULL"),
    )

    # --- histórico de lotação ---
    op.create_table(
        "animal_lot_assignments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "animal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("animals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("lote", sa.String(length=64), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column(
            "source_import_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("imports.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_by", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source IN ('legacy_baseline', 'import', 'manual')",
            name="ck_animal_lot_assignments_source",
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from",
            name="ck_animal_lot_assignments_period",
        ),
    )
    # No máximo uma lotação vigente por animal.
    op.create_index(
        "uq_animal_lot_assignments_current",
        "animal_lot_assignments",
        ["animal_id"],
        unique=True,
        postgresql_where=sa.text("valid_to IS NULL"),
    )

    # --- importação administrativa da baseline ---
    op.create_table(
        "baseline_imports",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "farm_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("farms.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_path", sa.String(length=512), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("animal_count", sa.Integer(), nullable=False),
        sa.Column("measurement_count", sa.Integer(), nullable=False),
        sa.Column("approved_by", sa.String(length=255), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )

    # --- official_measurements: proveniência declarada ---
    # O default 'ocr_review' preserva o significado de tudo que já existe:
    # toda medição gravada até aqui veio, de fato, de revisão de OCR.
    op.add_column(
        "official_measurements",
        sa.Column(
            "provenance",
            sa.String(length=32),
            server_default=sa.text("'ocr_review'"),
            nullable=False,
        ),
    )
    op.add_column(
        "official_measurements",
        sa.Column(
            "baseline_import_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("baseline_imports.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.add_column(
        "official_measurements",
        sa.Column("lote_observado", sa.String(length=64), nullable=True),
    )
    op.create_check_constraint(
        "ck_official_measurements_provenance",
        "official_measurements",
        "provenance IN ('ocr_review', 'legacy_baseline')",
    )
    op.drop_constraint(
        "ck_official_measurements_active_review_provenance",
        "official_measurements",
        type_="check",
    )
    op.create_check_constraint(
        "ck_official_measurements_active_review_provenance",
        "official_measurements",
        _NEW_PROVENANCE_CHECK,
    )

    # O trigger de 0001 exigia uma ReviewDecision aprovada para toda medição
    # ativa. Ele passa a reconhecer a origem declarada, mantendo o mesmo rigor
    # em ambos os caminhos: a baseline também exige um registro de importação
    # aprovado e um aprovador correspondente.
    op.execute(_ENSURE_APPROVAL_FUNCTION_V2)
    # Espelha, para baseline_imports, a proteção que 0001 deu a review_decisions:
    # não se altera a proveniência de uma medição ativa.
    op.execute(
        """
        CREATE FUNCTION preserve_active_baseline_import() RETURNS trigger AS $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM official_measurements
                WHERE baseline_import_id = OLD.id AND status = 'active'
            ) AND NEW.approved_by <> OLD.approved_by THEN
                RAISE EXCEPTION 'cannot alter approval provenance of an active measurement';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER baseline_imports_preserve_active_provenance
        BEFORE UPDATE ON baseline_imports
        FOR EACH ROW EXECUTE FUNCTION preserve_active_baseline_import();
        """
    )
    op.execute(
        "CREATE TRIGGER baseline_imports_set_updated_at BEFORE UPDATE ON baseline_imports "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
    op.execute(
        "CREATE TRIGGER animal_lot_assignments_set_updated_at BEFORE UPDATE ON "
        "animal_lot_assignments FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def downgrade() -> None:
    # O schema anterior não sabe representar uma medição da baseline: seu CHECK
    # exige ReviewDecision para toda medição ativa. Reverter com dados da
    # baseline presentes só seria possível destruindo ou falsificando essas
    # linhas, então a reversão para aqui e devolve a decisão ao operador.
    connection = op.get_bind()
    legacy_rows = connection.execute(
        sa.text(
            "SELECT count(*) FROM official_measurements "
            "WHERE provenance = 'legacy_baseline'"
        )
    ).scalar_one()
    if legacy_rows:
        raise RuntimeError(
            f"downgrade bloqueado: {legacy_rows} medições com provenance="
            "'legacy_baseline' existem e não cabem no schema anterior. "
            "Decida explicitamente o que fazer com elas (exportar, remover ou "
            "manter o schema atual) antes de reverter esta migration."
        )

    op.execute(
        "DROP TRIGGER IF EXISTS animal_lot_assignments_set_updated_at ON animal_lot_assignments"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS baseline_imports_set_updated_at ON baseline_imports"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS baseline_imports_preserve_active_provenance ON baseline_imports"
    )
    op.execute("DROP FUNCTION IF EXISTS preserve_active_baseline_import()")
    op.execute(_ENSURE_APPROVAL_FUNCTION_V1)
    op.drop_constraint(
        "ck_official_measurements_active_review_provenance",
        "official_measurements",
        type_="check",
    )
    op.create_check_constraint(
        "ck_official_measurements_active_review_provenance",
        "official_measurements",
        _OLD_PROVENANCE_CHECK,
    )
    op.drop_constraint(
        "ck_official_measurements_provenance",
        "official_measurements",
        type_="check",
    )
    op.drop_column("official_measurements", "lote_observado")
    op.drop_column("official_measurements", "baseline_import_id")
    op.drop_column("official_measurements", "provenance")

    op.drop_table("baseline_imports")

    op.drop_index(
        "uq_animal_lot_assignments_current", table_name="animal_lot_assignments"
    )
    op.drop_table("animal_lot_assignments")

    op.drop_index("uq_animals_farm_legacy_id", table_name="animals")
    op.drop_index("uq_animals_farm_brinco", table_name="animals")
    for column in (
        "observacoes",
        "peso",
        "nascimento",
        "ultimo_parto",
        "status",
        "situacao",
        "numero_legado",
        "legacy_id",
        "brinco_origem",
        "brinco",
    ):
        op.drop_column("animals", column)
