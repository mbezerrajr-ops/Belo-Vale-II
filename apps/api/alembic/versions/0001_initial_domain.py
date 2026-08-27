"""Create the auditable photo-ingestion domain.

Revision ID: 0001_initial_domain
Revises:
Create Date: 2026-08-27
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_initial_domain"
down_revision = None
branch_labels = None
depends_on = None


uuid = postgresql.UUID(as_uuid=True)
jsonb = postgresql.JSONB(astext_type=sa.Text())
timestamp = sa.DateTime(timezone=True)


def audit_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "farms",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("code", sa.String(length=64), unique=True),
        *audit_columns(),
    )
    op.create_table(
        "animals",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("farm_id", uuid, sa.ForeignKey("farms.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("identifier", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255)),
        *audit_columns(),
    )
    op.create_index("uq_animals_farm_identifier", "animals", ["farm_id", "identifier"], unique=True)
    op.create_table(
        "imports",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("farm_id", uuid, sa.ForeignKey("farms.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=255)),
        sa.Column("initiated_by", sa.String(length=255)),
        *audit_columns(),
    )
    op.create_table(
        "image_assets",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("farm_id", uuid, sa.ForeignKey("farms.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("import_id", uuid, sa.ForeignKey("imports.id", ondelete="SET NULL")),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("object_key", sa.String(length=512)),
        sa.Column("media_type", sa.String(length=128)),
        sa.Column("byte_size", sa.Integer()),
        *audit_columns(),
    )
    op.create_index("uq_image_assets_farm_sha256", "image_assets", ["farm_id", "sha256"], unique=True)
    op.create_table(
        "extraction_runs",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("image_asset_id", uuid, sa.ForeignKey("image_assets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("model_name", sa.String(length=255)),
        sa.Column("raw_response", jsonb),
        sa.Column("started_at", timestamp),
        sa.Column("completed_at", timestamp),
        *audit_columns(),
    )
    op.create_table(
        "extracted_lines",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("extraction_run_id", uuid, sa.ForeignKey("extraction_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("raw_values", jsonb, nullable=False),
        sa.Column("normalized_values", jsonb),
        sa.Column("confidence", sa.Float()),
        sa.Column("crop_coordinates", jsonb),
        *audit_columns(),
    )
    op.create_table(
        "validation_alerts",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("extracted_line_id", uuid, sa.ForeignKey("extracted_lines.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", jsonb),
        *audit_columns(),
    )
    op.create_table(
        "review_decisions",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("extracted_line_id", uuid, sa.ForeignKey("extracted_lines.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("corrected_values", jsonb),
        sa.Column("reason", sa.Text()),
        sa.Column("expected_version", sa.Integer(), nullable=False),
        *audit_columns(),
    )
    op.create_table(
        "official_measurements",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("animal_id", uuid, sa.ForeignKey("animals.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("extracted_line_id", uuid, sa.ForeignKey("extracted_lines.id", ondelete="SET NULL")),
        sa.Column("measured_on", sa.Date(), nullable=False),
        sa.Column("values", jsonb, nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reviewed_by", sa.String(length=255)),
        sa.CheckConstraint("status IN ('active', 'superseded')", name="ck_official_measurements_status"),
        *audit_columns(),
    )
    op.create_index(
        "uq_official_measurements_active_animal_measured_on",
        "official_measurements",
        ["animal_id", "measured_on"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("farm_id", uuid, sa.ForeignKey("farms.id", ondelete="SET NULL")),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("entity_type", sa.String(length=128), nullable=False),
        sa.Column("entity_id", uuid, nullable=False),
        sa.Column("previous_value", jsonb),
        sa.Column("new_value", jsonb),
        *audit_columns(),
    )


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_index("uq_official_measurements_active_animal_measured_on", table_name="official_measurements")
    op.drop_table("official_measurements")
    op.drop_table("review_decisions")
    op.drop_table("validation_alerts")
    op.drop_table("extracted_lines")
    op.drop_table("extraction_runs")
    op.drop_index("uq_image_assets_farm_sha256", table_name="image_assets")
    op.drop_table("image_assets")
    op.drop_table("imports")
    op.drop_index("uq_animals_farm_identifier", table_name="animals")
    op.drop_table("animals")
    op.drop_table("farms")
