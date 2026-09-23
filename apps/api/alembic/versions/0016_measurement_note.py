"""A observação da pesagem, junto da leitura.

A folha de coleta tem uma coluna de observação ("→ Seca", "→ 3º Lote"), e até
aqui ela se perdia na digitação e na importação. Passa a ser guardada na
própria leitura. Manhã e tarde vão no `values` da leitura, ao lado do total, e
não precisam de coluna.

Uma coluna nova, anulável e sem valor padrão (metadado puro em PostgreSQL),
com limite de tamanho: é anotação de curral, não texto livre.

Revision ID: 0016_measurement_note
Revises: 0015_merged_animals
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016_measurement_note"
down_revision = "0015_merged_animals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("official_measurements", sa.Column("observacao", sa.String(200), nullable=True))


def downgrade() -> None:
    # Descer apagaria as observações anotadas nas pesagens.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM official_measurements WHERE observacao IS NOT NULL) THEN
                RAISE EXCEPTION 'há leituras com observação; o downgrade as apagaria';
            END IF;
        END $$;
        """
    )
    op.drop_column("official_measurements", "observacao")
