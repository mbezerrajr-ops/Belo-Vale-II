"""Correção da data de um arquivo lido, de uma vez para todas as propostas.

O leitor pode errar a data do cabeçalho (na primeira folha real, 25/08/2026
virou 2024). A fonte continua imutável — é a prova do que foi lido —, mas
ganha colunas próprias para a data corrigida, com quem corrigiu e quando. O
trigger passa a aceitar mudança só nessas colunas.

Revision ID: 0011_source_date_correction
Revises: 0010_event_proposals
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011_source_date_correction"
down_revision = "0010_event_proposals"
branch_labels = None
depends_on = None

_CORRECTION_COLUMNS = (
    "corrected_reference_date",
    "corrected_by_user_id",
    "corrected_at",
    "updated_at",
)


def upgrade() -> None:
    op.add_column(
        "event_proposal_sources", sa.Column("corrected_reference_date", sa.Date(), nullable=True)
    )
    op.add_column(
        "event_proposal_sources",
        sa.Column(
            "corrected_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.add_column(
        "event_proposal_sources",
        sa.Column("corrected_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_event_proposal_sources_correction",
        "event_proposal_sources",
        "(corrected_reference_date IS NULL AND corrected_by_user_id IS NULL AND corrected_at IS NULL)"
        " OR (corrected_reference_date IS NOT NULL AND corrected_by_user_id IS NOT NULL"
        " AND corrected_at IS NOT NULL)",
    )
    removed = " - ".join(f"'{column}'" for column in _CORRECTION_COLUMNS)
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION forbid_event_proposal_source_update() RETURNS trigger AS $$
        BEGIN
            -- O que foi lido não muda; só a correção da data (e o carimbo).
            IF (to_jsonb(NEW) - {removed}) IS DISTINCT FROM (to_jsonb(OLD) - {removed}) THEN
                RAISE EXCEPTION 'event proposal sources are immutable';
            END IF;
            IF OLD.corrected_reference_date IS NOT NULL AND NEW.corrected_reference_date IS NULL THEN
                RAISE EXCEPTION 'a date correction cannot be erased';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM event_proposal_sources WHERE corrected_reference_date IS NOT NULL
            ) THEN
                RAISE EXCEPTION 'há datas corrigidas; o downgrade apagaria essa correção';
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION forbid_event_proposal_source_update() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'event proposal sources are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.drop_constraint(
        "ck_event_proposal_sources_correction", "event_proposal_sources", type_="check"
    )
    op.drop_column("event_proposal_sources", "corrected_at")
    op.drop_column("event_proposal_sources", "corrected_by_user_id")
    op.drop_column("event_proposal_sources", "corrected_reference_date")
