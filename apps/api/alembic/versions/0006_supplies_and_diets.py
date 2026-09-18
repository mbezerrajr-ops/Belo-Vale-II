"""Insumos, histórico de preço, dieta por lote e preço do leite.

Estes dados existem na baseline legada (4 insumos e o preço do leite) e são a
base do cálculo de custo de alimentação — que o painel do rebanho usa e que
não tinha onde existir no schema novo.

Revision ID: 0006_supplies_and_diets
Revises: 0005_refresh_tokens
Create Date: 2026-09-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0006_supplies_and_diets"
down_revision = "0005_refresh_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # O preço do leite é uma configuração da fazenda, não de um animal.
    op.add_column(
        "farms",
        sa.Column("milk_price_per_liter", sa.Numeric(precision=10, scale=4), nullable=True),
    )

    op.create_table(
        "supplies",
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
        sa.Column("legacy_id", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("price_per_kg", sa.Numeric(precision=10, scale=5), nullable=False),
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
        sa.CheckConstraint("price_per_kg >= 0", name="ck_supplies_price_positive"),
    )
    op.create_index(
        "uq_supplies_farm_name", "supplies", ["farm_id", "name"], unique=True
    )
    op.create_index(
        "uq_supplies_farm_legacy_id",
        "supplies",
        ["farm_id", "legacy_id"],
        unique=True,
        postgresql_where=sa.text("legacy_id IS NOT NULL"),
    )

    # Preço é evento temporal, como medição: um preço novo acrescenta ao
    # histórico em vez de apagar o anterior.
    op.create_table(
        "supply_prices",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "supply_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("supplies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("price_per_kg", sa.Numeric(precision=10, scale=5), nullable=False),
        sa.Column("effective_on", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("recorded_by", sa.String(length=255), nullable=True),
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
            "source IN ('legacy_baseline', 'manual')", name="ck_supply_prices_source"
        ),
    )
    op.create_index(
        "uq_supply_prices_effective",
        "supply_prices",
        ["supply_id", "effective_on"],
        unique=True,
    )

    # A dieta é por lote, não por animal: é assim que a fazenda controla o
    # arraçoamento, e é o que torna o custo por vaca uma divisão do lote.
    op.create_table(
        "supply_diets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "supply_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("supplies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("lote", sa.String(length=64), nullable=False),
        sa.Column("kg_per_day", sa.Numeric(precision=10, scale=3), nullable=False),
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
        sa.CheckConstraint("kg_per_day >= 0", name="ck_supply_diets_positive"),
    )
    op.create_index(
        "uq_supply_diets_lote", "supply_diets", ["supply_id", "lote"], unique=True
    )

    for table in ("supplies", "supply_prices", "supply_diets"):
        op.execute(
            f"CREATE TRIGGER {table}_set_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )


def downgrade() -> None:
    for table in ("supply_diets", "supply_prices", "supplies"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_set_updated_at ON {table}")
    op.drop_table("supply_diets")
    op.drop_table("supply_prices")
    op.drop_index("uq_supplies_farm_legacy_id", table_name="supplies")
    op.drop_index("uq_supplies_farm_name", table_name="supplies")
    op.drop_table("supplies")
    op.drop_column("farms", "milk_price_per_liter")
