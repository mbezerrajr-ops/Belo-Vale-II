"""Uso diário: lançamento manual de produção, baixa de animal e senha provisória.

Três mudanças que tornam o sistema utilizável no dia a dia da fazenda:

- **Lançamento manual.** Até aqui uma medição só nascia de uma revisão de OCR
  ou da baseline. O funcionário que anota o leite no curral precisa lançar
  direto, então surge a proveniência `manual_entry` — com o mesmo rigor das
  outras duas: o banco exige saber *quem* lançou, e esse alguém precisa ser
  uma conta real cujo e-mail bate com o responsável gravado.
- **Baixa de animal.** Venda, morte e descarte deixam de ser uma edição solta
  do campo `status`: ganham data e motivo, e o banco garante que os dois
  andam juntos.
- **Senha provisória.** O administrador redefine a senha de quem esqueceu; a
  senha gerada expira e obriga a troca no primeiro acesso.

Revision ID: 0008_daily_use
Revises: 0007_lot_kind
Create Date: 2026-09-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0008_daily_use"
down_revision = "0007_lot_kind"
branch_labels = None
depends_on = None


_PROVENANCE_V2 = "provenance IN ('ocr_review', 'legacy_baseline')"
_PROVENANCE_V3 = "provenance IN ('ocr_review', 'legacy_baseline', 'manual_entry')"

_ACTIVE_CHECK_V2 = (
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

#: Cópia fiel da versão de 0004, para o downgrade restaurar exatamente.
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

#: O lançamento manual tem o mesmo rigor das outras origens: o responsável
#: gravado precisa ser uma conta existente e bater com quem lançou. Um
#: `reviewed_by` digitado à mão, sem conta por trás, é recusado pelo banco.
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

#: Motivos de baixa. Fechados de propósito: um texto livre viraria dez
#: grafias de "venda" e impediria qualquer contagem.
EXIT_REASONS = ("venda", "morte", "descarte", "doacao", "outro")


def upgrade() -> None:
    # --- lançamento manual de produção ---
    # `voided`: lançamento anulado, por exemplo na vaca errada. Diferente de
    # `superseded`, não tem sucessor — e nenhum dos dois some do banco.
    op.drop_constraint(
        "ck_official_measurements_status", "official_measurements", type_="check"
    )
    op.create_check_constraint(
        "ck_official_measurements_status",
        "official_measurements",
        "status IN ('active', 'superseded', 'voided')",
    )
    op.add_column(
        "official_measurements",
        sa.Column(
            "entered_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    # Uma correção aponta para a medição que substituiu: o histórico se lê
    # pelo próprio dado, sem depender só da trilha de auditoria.
    op.add_column(
        "official_measurements",
        sa.Column(
            "supersedes_measurement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("official_measurements.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.drop_constraint(
        "ck_official_measurements_provenance",
        "official_measurements",
        type_="check",
    )
    op.create_check_constraint(
        "ck_official_measurements_provenance",
        "official_measurements",
        _PROVENANCE_V3,
    )
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
    op.execute(_ENSURE_APPROVAL_FUNCTION_V3)

    # --- baixa de animal ---
    op.add_column("animals", sa.Column("exited_on", sa.Date(), nullable=True))
    op.add_column("animals", sa.Column("exit_reason", sa.String(16), nullable=True))
    op.add_column("animals", sa.Column("exit_notes", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_animals_exit_reason",
        "animals",
        "exit_reason IS NULL OR exit_reason IN ("
        + ", ".join(f"'{reason}'" for reason in EXIT_REASONS)
        + ")",
    )
    # Data sem motivo, ou motivo sem data, é uma baixa pela metade.
    op.create_check_constraint(
        "ck_animals_exit_complete",
        "animals",
        "(exited_on IS NULL) = (exit_reason IS NULL)",
    )

    # --- senha provisória ---
    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "users",
        sa.Column("password_expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    # O schema anterior não representa medição lançada à mão. Apagar essas
    # linhas destruiria produção real, então a reversão para e devolve a
    # decisão a quem opera.
    connection = op.get_bind()
    manual_rows = connection.execute(
        sa.text(
            "SELECT count(*) FROM official_measurements "
            "WHERE provenance = 'manual_entry'"
        )
    ).scalar_one()
    if manual_rows:
        raise RuntimeError(
            f"downgrade bloqueado: {manual_rows} medições lançadas à mão "
            "(provenance='manual_entry') não cabem no schema anterior. "
            "Exporte-as ou mantenha o schema atual antes de reverter."
        )
    voided_rows = connection.execute(
        sa.text(
            "SELECT count(*) FROM official_measurements WHERE status = 'voided'"
        )
    ).scalar_one()
    if voided_rows:
        raise RuntimeError(
            f"downgrade bloqueado: {voided_rows} medições anuladas não cabem no "
            "schema anterior, que só conhece 'active' e 'superseded'."
        )
    exited_rows = connection.execute(
        sa.text("SELECT count(*) FROM animals WHERE exited_on IS NOT NULL")
    ).scalar_one()
    if exited_rows:
        raise RuntimeError(
            f"downgrade bloqueado: {exited_rows} animais com baixa registrada "
            "perderiam a data e o motivo da saída."
        )

    op.drop_column("users", "password_expires_at")
    op.drop_column("users", "must_change_password")

    op.drop_constraint("ck_animals_exit_complete", "animals", type_="check")
    op.drop_constraint("ck_animals_exit_reason", "animals", type_="check")
    op.drop_column("animals", "exit_notes")
    op.drop_column("animals", "exit_reason")
    op.drop_column("animals", "exited_on")

    op.execute(_ENSURE_APPROVAL_FUNCTION_V2)
    op.drop_constraint(
        "ck_official_measurements_status", "official_measurements", type_="check"
    )
    op.create_check_constraint(
        "ck_official_measurements_status",
        "official_measurements",
        "status IN ('active', 'superseded')",
    )
    op.drop_constraint(
        "ck_official_measurements_active_review_provenance",
        "official_measurements",
        type_="check",
    )
    op.create_check_constraint(
        "ck_official_measurements_active_review_provenance",
        "official_measurements",
        _ACTIVE_CHECK_V2,
    )
    op.drop_constraint(
        "ck_official_measurements_provenance",
        "official_measurements",
        type_="check",
    )
    op.create_check_constraint(
        "ck_official_measurements_provenance",
        "official_measurements",
        _PROVENANCE_V2,
    )
    op.drop_column("official_measurements", "supersedes_measurement_id")
    op.drop_column("official_measurements", "entered_by_user_id")
