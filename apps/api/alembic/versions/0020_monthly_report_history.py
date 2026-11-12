"""Vigência do leite e da dieta para relatórios mensais sem retroagir snapshots."""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "0020_monthly_report_history"
down_revision = "0019_single_farm_per_user"
branch_labels = depends_on = None


def common():
    return [
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("effective_on", sa.Date(), nullable=False),
        sa.Column("recorded_by", sa.String(255)),
        sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def upgrade():
    op.create_table("milk_price_history", *common(),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("price_per_liter", sa.Numeric(10, 5)),
        sa.CheckConstraint("price_per_liter >= 0", name="ck_milk_price_history_nonnegative"))
    op.create_index("uq_milk_price_history_date", "milk_price_history", ["farm_id", "effective_on"], unique=True)
    op.create_table("supply_diet_history", *common(),
        sa.Column("supply_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("supplies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lote", sa.String(64), nullable=False),
        sa.Column("kg_per_day", sa.Numeric(10, 3), nullable=False),
        sa.CheckConstraint("kg_per_day >= 0", name="ck_supply_diet_history_nonnegative"))
    op.create_index("uq_supply_diet_history_date", "supply_diet_history", ["supply_id", "lote", "effective_on"], unique=True)
    # A migração conhece os valores de hoje, não os de meses anteriores.
    op.execute("""INSERT INTO milk_price_history(farm_id,effective_on,price_per_liter,source)
      SELECT id,(CURRENT_TIMESTAMP AT TIME ZONE timezone)::date,milk_price_per_liter,'snapshot' FROM farms
      WHERE milk_price_per_liter IS NOT NULL""")
    op.execute("""INSERT INTO supply_diet_history(supply_id,lote,effective_on,kg_per_day,source)
      SELECT d.supply_id,d.lote,(CURRENT_TIMESTAMP AT TIME ZONE f.timezone)::date,d.kg_per_day,'snapshot'
      FROM supply_diets d JOIN supplies s ON s.id=d.supply_id JOIN farms f ON f.id=s.farm_id""")


def downgrade():
    op.drop_table("supply_diet_history")
    op.drop_table("milk_price_history")
