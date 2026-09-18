"""Importação de produção por arquivo (CSV, XLSX, PDF).

A coleta de leite chega em arquivo — era assim no sistema antigo. Cada envio
vira um registro imutável em `production_imports`, com o próprio arquivo
guardado, e cada leitura criada por ele aponta para esse registro. Assim toda
leitura importada responde a três perguntas: de qual arquivo veio, quem
enviou e em que modo.

A nova proveniência `file_import` tem o mesmo rigor das outras: o banco
recusa uma leitura ativa que não aponte para uma importação real, feita por
uma conta real cujo e-mail bate com o responsável gravado.

Revision ID: 0009_production_imports
Revises: 0008_daily_use
Create Date: 2026-09-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0009_production_imports"
down_revision = "0008_daily_use"
branch_labels = None
depends_on = None

#: Limite do arquivo guardado. Uma coleta de 400 vacas em CSV tem poucos KB;
#: um PDF de relatório, algumas centenas.
MAX_BYTES = 5 * 1024 * 1024

_PROVENANCE_V3 = "provenance IN ('ocr_review', 'legacy_baseline', 'manual_entry')"
_PROVENANCE_V4 = (
    "provenance IN ('ocr_review', 'legacy_baseline', 'manual_entry', 'file_import')"
)

_ACTIVE_CHECK_V3 = (
    "status <> 'active' OR ("
    " (provenance = 'ocr_review'"
    "  AND review_decision_id IS NOT NULL"
    "  AND reviewed_by IS NOT NULL AND length(btrim(reviewed_by)) > 0)"
    " OR"
    " (provenance = 'legacy_baseline'"
    "  AND baseline_import_id IS NOT NULL"
    "  AND reviewed_by IS NOT NULL AND length(btrim(reviewed_by)) > 0)"
    " OR"
    " (provenance = 'manual_entry'"
    "  AND entered_by_user_id IS NOT NULL"
    "  AND reviewed_by IS NOT NULL AND length(btrim(reviewed_by)) > 0)"
    ")"
)
_ACTIVE_CHECK_V4 = (
    "status <> 'active' OR ("
    " (provenance = 'ocr_review'"
    "  AND review_decision_id IS NOT NULL"
    "  AND reviewed_by IS NOT NULL AND length(btrim(reviewed_by)) > 0)"
    " OR"
    " (provenance = 'legacy_baseline'"
    "  AND baseline_import_id IS NOT NULL"
    "  AND reviewed_by IS NOT NULL AND length(btrim(reviewed_by)) > 0)"
    " OR"
    " (provenance = 'manual_entry'"
    "  AND entered_by_user_id IS NOT NULL"
    "  AND reviewed_by IS NOT NULL AND length(btrim(reviewed_by)) > 0)"
    " OR"
    " (provenance = 'file_import'"
    "  AND production_import_id IS NOT NULL"
    "  AND reviewed_by IS NOT NULL AND length(btrim(reviewed_by)) > 0)"
    ")"
)

#: Cópia fiel da versão de 0008, para o downgrade restaurar exatamente.
_ENSURE_APPROVAL_FUNCTION_V3 = """
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
        ELSIF NEW.provenance = 'manual_entry' THEN
            IF NOT EXISTS (
                SELECT 1
                FROM users
                WHERE id = NEW.entered_by_user_id
                  AND email = NEW.reviewed_by
            ) THEN
                RAISE EXCEPTION 'active manual measurements require an existing user matching the recorded actor';
            END IF;
        ELSE
            RAISE EXCEPTION 'unknown measurement provenance: %', NEW.provenance;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

_ENSURE_APPROVAL_FUNCTION_V4 = """
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
        ELSIF NEW.provenance = 'manual_entry' THEN
            IF NOT EXISTS (
                SELECT 1
                FROM users
                WHERE id = NEW.entered_by_user_id
                  AND email = NEW.reviewed_by
            ) THEN
                RAISE EXCEPTION 'active manual measurements require an existing user matching the recorded actor';
            END IF;
        ELSIF NEW.provenance = 'file_import' THEN
            IF NOT EXISTS (
                SELECT 1
                FROM production_imports pi
                JOIN users u ON u.id = pi.imported_by_user_id
                WHERE pi.id = NEW.production_import_id
                  AND pi.measured_on = NEW.measured_on
                  AND u.email = NEW.reviewed_by
            ) THEN
                RAISE EXCEPTION 'active imported measurements require a production import of the same date by the recorded actor';
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
    op.create_table(
        "production_imports",
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
        sa.Column("measured_on", sa.Date(), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("file_format", sa.String(8), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        # O arquivo original, byte a byte: a prova do que foi enviado.
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "imported_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("summary", postgresql.JSONB(), nullable=False),
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
            "file_format IN ('csv', 'xlsx', 'pdf')",
            name="ck_production_imports_format",
        ),
        sa.CheckConstraint(
            "mode IN ('new_only', 'replace')", name="ck_production_imports_mode"
        ),
        # Substituir uma coleta é decisão com consequência: sem motivo, não vai.
        sa.CheckConstraint(
            "mode <> 'replace' OR (reason IS NOT NULL AND length(btrim(reason)) >= 3)",
            name="ck_production_imports_replace_reason",
        ),
        sa.CheckConstraint(
            f"byte_size > 0 AND byte_size <= {MAX_BYTES}",
            name="ck_production_imports_size",
        ),
    )
    # O mesmo arquivo, na mesma data e no mesmo modo, é uma importação só:
    # reenviar não duplica nada.
    op.create_index(
        "uq_production_imports_same_file",
        "production_imports",
        ["farm_id", "measured_on", "sha256", "mode"],
        unique=True,
    )
    # Registro de importação é prova: nasce completo e não muda depois.
    op.execute(
        """
        CREATE FUNCTION forbid_production_import_update() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'production imports are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "CREATE TRIGGER production_imports_immutable BEFORE UPDATE ON production_imports "
        "FOR EACH ROW EXECUTE FUNCTION forbid_production_import_update()"
    )

    op.add_column(
        "official_measurements",
        sa.Column(
            "production_import_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("production_imports.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.drop_constraint(
        "ck_official_measurements_provenance", "official_measurements", type_="check"
    )
    op.create_check_constraint(
        "ck_official_measurements_provenance", "official_measurements", _PROVENANCE_V4
    )
    op.drop_constraint(
        "ck_official_measurements_active_review_provenance",
        "official_measurements",
        type_="check",
    )
    op.create_check_constraint(
        "ck_official_measurements_active_review_provenance",
        "official_measurements",
        _ACTIVE_CHECK_V4,
    )
    op.execute(_ENSURE_APPROVAL_FUNCTION_V4)


def downgrade() -> None:
    # O schema anterior não sabe o que é uma leitura importada de arquivo.
    # Apagá-las destruiria produção real e o arquivo que a prova.
    connection = op.get_bind()
    imports = connection.execute(
        sa.text("SELECT count(*) FROM production_imports")
    ).scalar_one()
    if imports:
        raise RuntimeError(
            f"downgrade bloqueado: {imports} importações de produção registradas. "
            "Exporte-as ou mantenha o schema atual antes de reverter."
        )

    op.execute(_ENSURE_APPROVAL_FUNCTION_V3)
    op.drop_constraint(
        "ck_official_measurements_active_review_provenance",
        "official_measurements",
        type_="check",
    )
    op.create_check_constraint(
        "ck_official_measurements_active_review_provenance",
        "official_measurements",
        _ACTIVE_CHECK_V3,
    )
    op.drop_constraint(
        "ck_official_measurements_provenance", "official_measurements", type_="check"
    )
    op.create_check_constraint(
        "ck_official_measurements_provenance", "official_measurements", _PROVENANCE_V3
    )
    op.drop_column("official_measurements", "production_import_id")

    op.execute("DROP TRIGGER IF EXISTS production_imports_immutable ON production_imports")
    op.execute("DROP FUNCTION IF EXISTS forbid_production_import_update()")
    op.drop_index("uq_production_imports_same_file", table_name="production_imports")
    op.drop_table("production_imports")
