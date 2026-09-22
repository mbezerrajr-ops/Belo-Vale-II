"""A ficha duplicada é juntada à certa, em vez de corrigida medição por medição.

A conferência de 25/08 achou vacas com duas fichas — uma com o brinco, outra
sem, cada uma com parte da produção. Até aqui a correção era anular e
relançar, uma medição por vez. Juntar faz isso de uma vez, com auditoria, e a
ficha duplicada não some: fica arquivada, apontando para a que ficou, porque
as medições anuladas nela continuam sendo prova.

Duas colunas novas, anuláveis e sem valor padrão (metadado puro em
PostgreSQL), e três regras no banco:

- quem aponta tem data, e quem tem data aponta;
- uma ficha não é juntada a si mesma;
- a ficha juntada não tem brinco — assim nenhum arquivo novo a alcança.

Revision ID: 0015_merged_animals
Revises: 0014_failure_code
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0015_merged_animals"
down_revision = "0014_failure_code"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "animals",
        sa.Column(
            "merged_into_id",
            UUID(as_uuid=True),
            sa.ForeignKey("animals.id", ondelete="RESTRICT", name="fk_animals_merged_into_id"),
            nullable=True,
        ),
    )
    op.add_column("animals", sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_animals_merge_complete", "animals", "(merged_into_id IS NULL) = (merged_at IS NULL)"
    )
    op.create_check_constraint(
        "ck_animals_merge_not_self", "animals", "merged_into_id IS NULL OR merged_into_id <> id"
    )
    op.create_check_constraint(
        "ck_animals_merged_without_brinco", "animals", "merged_into_id IS NULL OR brinco IS NULL"
    )


def downgrade() -> None:
    # Descer apagaria a informação de quais fichas foram juntadas: as
    # medições delas já foram relançadas, mas a ficha arquivada voltaria a
    # parecer um animal do rebanho.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM animals WHERE merged_into_id IS NOT NULL) THEN
                RAISE EXCEPTION 'há fichas juntadas; o downgrade as devolveria ao rebanho';
            END IF;
        END $$;
        """
    )
    op.drop_constraint("ck_animals_merged_without_brinco", "animals", type_="check")
    op.drop_constraint("ck_animals_merge_not_self", "animals", type_="check")
    op.drop_constraint("ck_animals_merge_complete", "animals", type_="check")
    op.drop_column("animals", "merged_at")
    op.drop_column("animals", "merged_into_id")
