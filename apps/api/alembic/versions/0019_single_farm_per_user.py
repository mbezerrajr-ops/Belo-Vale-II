"""Garantir uma única fazenda ativa por usuário sem apagar vínculos históricos."""

import sqlalchemy as sa
from alembic import op

revision = "0019_single_farm_per_user"
down_revision = "0018_farm_integrity"
branch_labels = depends_on = None


def upgrade():
    # Dados de fazendas existentes não podem ser escolhidos/removidos por palpite.
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT user_id FROM farm_memberships WHERE is_active GROUP BY user_id HAVING count(*) > 1) THEN
        RAISE EXCEPTION 'há usuários com acesso a várias fazendas: defina o único vínculo ativo de cada um antes de atualizar; nenhum dado foi removido';
      END IF;
    END $$""")
    op.create_index(
        "uq_farm_membership_active_user",
        "farm_memberships",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )


def downgrade():
    op.drop_index("uq_farm_membership_active_user", table_name="farm_memberships")
