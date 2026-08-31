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
        sa.Column("created_at", timestamp, server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", timestamp, server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    ]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.create_table(
        "farms",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("code", sa.String(length=64), unique=True),
        *audit_columns(),
    )
    op.create_table(
        "animals",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("farm_id", uuid, sa.ForeignKey("farms.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("identifier", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255)),
        *audit_columns(),
    )
    op.create_index("uq_animals_farm_identifier", "animals", ["farm_id", "identifier"], unique=True)
    op.create_table(
        "imports",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("farm_id", uuid, sa.ForeignKey("farms.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("source", sa.String(length=255)),
        sa.Column("initiated_by", sa.String(length=255)),
        *audit_columns(),
    )
    op.create_table(
        "image_assets",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
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
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("image_asset_id", uuid, sa.ForeignKey("image_assets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("model_name", sa.String(length=255)),
        sa.Column("raw_response", jsonb),
        sa.Column("started_at", timestamp),
        sa.Column("completed_at", timestamp),
        *audit_columns(),
    )
    op.create_table(
        "extracted_lines",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
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
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("extracted_line_id", uuid, sa.ForeignKey("extracted_lines.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", jsonb),
        *audit_columns(),
    )
    op.create_table(
        "review_decisions",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("extracted_line_id", uuid, sa.ForeignKey("extracted_lines.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("corrected_values", jsonb),
        sa.Column("reason", sa.Text()),
        sa.Column("expected_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint("decision IN ('approved', 'rejected')", name="ck_review_decisions_decision"),
        *audit_columns(),
    )
    op.create_table(
        "official_measurements",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("animal_id", uuid, sa.ForeignKey("animals.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("extracted_line_id", uuid, sa.ForeignKey("extracted_lines.id", ondelete="SET NULL")),
        sa.Column("review_decision_id", uuid, sa.ForeignKey("review_decisions.id", ondelete="RESTRICT")),
        sa.Column("measured_on", sa.Date(), nullable=False),
        sa.Column("values", jsonb, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reviewed_by", sa.String(length=255)),
        sa.CheckConstraint("status IN ('active', 'superseded')", name="ck_official_measurements_status"),
        sa.CheckConstraint(
            "status <> 'active' OR (review_decision_id IS NOT NULL AND reviewed_by IS NOT NULL AND length(btrim(reviewed_by)) > 0)",
            name="ck_official_measurements_active_review_provenance",
        ),
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
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("farm_id", uuid, sa.ForeignKey("farms.id", ondelete="SET NULL")),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("entity_type", sa.String(length=128), nullable=False),
        sa.Column("entity_id", uuid, nullable=False),
        sa.Column("previous_value", jsonb),
        sa.Column("new_value", jsonb),
        *audit_columns(),
    )
    op.execute(
        """
        CREATE FUNCTION set_updated_at() RETURNS trigger AS $$
        BEGIN
            NEW.updated_at = CURRENT_TIMESTAMP;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table_name in (
        "farms",
        "animals",
        "imports",
        "image_assets",
        "extraction_runs",
        "extracted_lines",
        "validation_alerts",
        "review_decisions",
        "official_measurements",
        "audit_events",
    ):
        op.execute(
            f"CREATE TRIGGER {table_name}_set_updated_at BEFORE UPDATE ON {table_name} "
            "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )
    op.execute(
        """
        CREATE FUNCTION ensure_active_measurement_approval() RETURNS trigger AS $$
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
    )
    op.execute(
        """
        CREATE TRIGGER official_measurements_require_approved_review
        BEFORE INSERT OR UPDATE ON official_measurements
        FOR EACH ROW EXECUTE FUNCTION ensure_active_measurement_approval();
        """
    )
    op.execute(
        """
        CREATE FUNCTION preserve_active_measurement_review() RETURNS trigger AS $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM official_measurements
                WHERE review_decision_id = OLD.id AND status = 'active'
            ) AND (NEW.decision <> 'approved' OR NEW.actor <> OLD.actor) THEN
                RAISE EXCEPTION 'cannot alter approval provenance of an active measurement';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER review_decisions_preserve_active_provenance
        BEFORE UPDATE OF decision, actor ON review_decisions
        FOR EACH ROW EXECUTE FUNCTION preserve_active_measurement_review();
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "0001_initial_domain is intentionally irreversible: raw OCR, corrections, and audit history must be retained."
    )
