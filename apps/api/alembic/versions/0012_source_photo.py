"""A fonte de propostas guarda de qual foto veio.

Quem revisa precisa ver a folha ao lado do que foi lido, sem trocar de tela.
A coluna é escrita no INSERT e nunca atualizada: a fonte continua imutável
(o trigger de 0010/0011 compara a linha inteira menos as colunas de correção
da data, e esta não está entre elas).

Revision ID: 0012_source_photo
Revises: 0011_source_date_correction
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012_source_photo"
down_revision = "0011_source_date_correction"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "event_proposal_sources",
        sa.Column(
            "image_asset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("image_assets.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("event_proposal_sources", "image_asset_id")
