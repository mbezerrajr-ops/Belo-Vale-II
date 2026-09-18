"""Propostas de eventos e caixa de revisão.

Fotos de caderno, anotações e áudios não trazem só produção: trazem partos,
secagens, vendas, mudanças de lote, observações. Um leitor (visão
computacional, transcrição — nas fases seguintes) transforma cada arquivo
num conjunto de **propostas**; nenhuma delas vira dado do rebanho sem que
uma pessoa aprove.

- `event_proposal_sources`: o conjunto de onde as propostas vieram, com a
  saída bruta do leitor guardada e imutável.
- `event_proposals`: uma proposta por evento. O que foi lido fica como veio
  (`raw_fields`); o que a pessoa aprovou fica à parte (`applied_payload`).
  Decidida, a proposta não muda mais.
- `official_measurements` ganha a proveniência `proposal_review`, com o mesmo
  rigor das outras: só nasce de uma proposta aprovada, pela conta gravada como
  responsável.

Revision ID: 0010_event_proposals
Revises: 0009_production_imports
Create Date: 2026-09-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0010_event_proposals"
down_revision = "0009_production_imports"
branch_labels = None
depends_on = None

EVENT_TYPES = ("production", "calving", "dry_off", "exit", "lot_change", "note")
SOURCE_KINDS = ("photo", "audio", "text")

_PROVENANCE_V4 = (
    "provenance IN ('ocr_review', 'legacy_baseline', 'manual_entry', 'file_import')"
)
_PROVENANCE_V5 = (
    "provenance IN ('ocr_review', 'legacy_baseline', 'manual_entry', "
    "'file_import', 'proposal_review')"
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
_ACTIVE_CHECK_V5 = _ACTIVE_CHECK_V4[:-1] + (
    " OR"
    " (provenance = 'proposal_review'"
    "  AND event_proposal_id IS NOT NULL"
    "  AND reviewed_by IS NOT NULL AND length(btrim(reviewed_by)) > 0)"
    ")"
)

_BRANCHES_V4 = """
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
            END IF;"""

_PROPOSAL_BRANCH = """
        ELSIF NEW.provenance = 'proposal_review' THEN
            IF NOT EXISTS (
                SELECT 1
                FROM event_proposals ep
                JOIN users u ON u.id = ep.decided_by_user_id
                WHERE ep.id = NEW.event_proposal_id
                  AND ep.status = 'approved'
                  AND ep.event_type = 'production'
                  AND ep.applied_animal_id = NEW.animal_id
                  AND u.email = NEW.reviewed_by
            ) THEN
                RAISE EXCEPTION 'active reviewed measurements require an approved production proposal for the same animal by the recorded actor';
            END IF;"""


def _function(branches: str) -> str:
    return (
        "CREATE OR REPLACE FUNCTION ensure_active_measurement_approval() "
        "RETURNS trigger AS $$\nBEGIN\n    IF NEW.status = 'active' THEN"
        + branches
        + """
        ELSE
            RAISE EXCEPTION 'unknown measurement provenance: %', NEW.provenance;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""
    )


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def _in(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


def upgrade() -> None:
    op.create_table(
        "event_proposal_sources",
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
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("extractor_name", sa.String(64), nullable=False),
        sa.Column("extractor_version", sa.String(64), nullable=False),
        # Data a que o conteúdo se refere, quando o leitor a encontrou
        # ("coleta de 25/08"). Serve de referência para datas incompletas.
        sa.Column("reference_date", sa.Date(), nullable=True),
        # Saída do leitor, como veio: a prova do que foi lido.
        sa.Column("raw_output", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        *_timestamps(),
        sa.CheckConstraint(f"kind IN {_in(SOURCE_KINDS)}", name="ck_event_proposal_sources_kind"),
    )

    op.create_table(
        "event_proposals",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("event_proposal_sources.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "farm_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("farms.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(16), nullable=False),
        sa.Column("brinco_lido", sa.String(64), nullable=True),
        sa.Column("nome_lido", sa.String(255), nullable=True),
        # Só pelo brinco. Nome nunca associa: vira sugestão na tela.
        sa.Column(
            "candidate_animal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("animals.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("raw_fields", postgresql.JSONB(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "evidence", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "confidence", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "alerts", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "decided_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column(
            "applied_animal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("animals.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("applied_payload", postgresql.JSONB(), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            f"event_type IN {_in(EVENT_TYPES)}", name="ck_event_proposals_event_type"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')", name="ck_event_proposals_status"
        ),
        sa.CheckConstraint(
            "status = 'pending' OR (decided_by_user_id IS NOT NULL AND decided_at IS NOT NULL)",
            name="ck_event_proposals_decided",
        ),
        sa.CheckConstraint(
            "status <> 'rejected' OR "
            "(decision_reason IS NOT NULL AND length(btrim(decision_reason)) >= 3)",
            name="ck_event_proposals_rejection_reason",
        ),
        sa.CheckConstraint(
            "status <> 'approved' OR "
            "(applied_animal_id IS NOT NULL AND applied_payload IS NOT NULL)",
            name="ck_event_proposals_applied",
        ),
    )
    op.create_index(
        "ix_event_proposals_inbox", "event_proposals", ["farm_id", "status", "created_at"]
    )
    op.create_index("ix_event_proposals_source", "event_proposals", ["source_id", "position"])

    # A saída do leitor e as propostas decididas são prova: não mudam.
    op.execute(
        """
        CREATE FUNCTION forbid_event_proposal_source_update() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'event proposal sources are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "CREATE TRIGGER event_proposal_sources_immutable BEFORE UPDATE ON "
        "event_proposal_sources FOR EACH ROW EXECUTE FUNCTION forbid_event_proposal_source_update()"
    )
    op.execute(
        """
        CREATE FUNCTION forbid_decided_proposal_update() RETURNS trigger AS $$
        BEGIN
            IF OLD.status <> 'pending' THEN
                RAISE EXCEPTION 'decided event proposals are immutable';
            END IF;
            IF NEW.raw_fields IS DISTINCT FROM OLD.raw_fields THEN
                RAISE EXCEPTION 'raw fields of an event proposal are immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "CREATE TRIGGER event_proposals_decided_immutable BEFORE UPDATE ON event_proposals "
        "FOR EACH ROW EXECUTE FUNCTION forbid_decided_proposal_update()"
    )

    op.add_column(
        "official_measurements",
        sa.Column(
            "event_proposal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("event_proposals.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.drop_constraint(
        "ck_official_measurements_provenance", "official_measurements", type_="check"
    )
    op.create_check_constraint(
        "ck_official_measurements_provenance", "official_measurements", _PROVENANCE_V5
    )
    op.drop_constraint(
        "ck_official_measurements_active_review_provenance",
        "official_measurements",
        type_="check",
    )
    op.create_check_constraint(
        "ck_official_measurements_active_review_provenance",
        "official_measurements",
        _ACTIVE_CHECK_V5,
    )
    op.execute(_function(_BRANCHES_V4 + _PROPOSAL_BRANCH))


def downgrade() -> None:
    connection = op.get_bind()
    proposals = connection.execute(sa.text("SELECT count(*) FROM event_proposals")).scalar_one()
    if proposals:
        raise RuntimeError(
            f"downgrade bloqueado: {proposals} propostas de eventos registradas, com "
            "decisões e evidências que o schema anterior não guarda."
        )

    op.execute(_function(_BRANCHES_V4))
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
    op.drop_constraint(
        "ck_official_measurements_provenance", "official_measurements", type_="check"
    )
    op.create_check_constraint(
        "ck_official_measurements_provenance", "official_measurements", _PROVENANCE_V4
    )
    op.drop_column("official_measurements", "event_proposal_id")

    op.execute("DROP TRIGGER IF EXISTS event_proposals_decided_immutable ON event_proposals")
    op.execute("DROP FUNCTION IF EXISTS forbid_decided_proposal_update()")
    op.execute(
        "DROP TRIGGER IF EXISTS event_proposal_sources_immutable ON event_proposal_sources"
    )
    op.execute("DROP FUNCTION IF EXISTS forbid_event_proposal_source_update()")
    op.drop_index("ix_event_proposals_source", table_name="event_proposals")
    op.drop_index("ix_event_proposals_inbox", table_name="event_proposals")
    op.drop_table("event_proposals")
    op.drop_table("event_proposal_sources")
