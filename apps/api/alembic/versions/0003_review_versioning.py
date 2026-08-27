"""Add optimistic versioning and candidate-match to extracted lines,
and declared lot/date context to imports.

Revision ID: 0003_review_versioning
Revises: 0002_server_auth
Create Date: 2026-08-27
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003_review_versioning"
down_revision = "0002_server_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "imports",
        sa.Column("declared_lot", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "imports",
        sa.Column("declared_measured_on", sa.Date(), nullable=True),
    )

    op.add_column(
        "extracted_lines",
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.add_column(
        "extracted_lines",
        sa.Column(
            "candidate_animal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("animals.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("extracted_lines", "candidate_animal_id")
    op.drop_column("extracted_lines", "version")
    op.drop_column("imports", "declared_measured_on")
    op.drop_column("imports", "declared_lot")
