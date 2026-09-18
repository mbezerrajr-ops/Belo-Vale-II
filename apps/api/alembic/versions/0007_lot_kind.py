"""Distingue lote de ordenha de grupo de manejo.

O campo `lote` da baseline mistura os dois, e a migração anterior gravou tudo
junto sem tipo. A distinção existia na plataforma legada (`LOTES_DIETA` e
`LOTES_MANEJO`) e precisa existir aqui: só o lote de ordenha tem dieta e
custo, enquanto os demais são áreas e categorias da fazenda.

Revision ID: 0007_lot_kind
Revises: 0006_supplies_and_diets
Create Date: 2026-09-18
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_lot_kind"
down_revision = "0006_supplies_and_diets"
branch_labels = None
depends_on = None

#: Os três lotes de ordenha da baseline. A lista vive em
#: `app/services/lot_kind.py`; ela é repetida aqui porque uma migration não
#: deve depender do código da aplicação, que muda com o tempo — o backfill
#: precisa produzir o mesmo resultado daqui a um ano.
_DIET_LOTS = ("LOTE 1", "LOTE 2", "LOTE 3")


def upgrade() -> None:
    op.add_column(
        "animal_lot_assignments",
        sa.Column("kind", sa.String(length=16), nullable=True),
    )

    # Backfill: comparação sem acento, caixa ou espaço extra, como o domínio faz.
    op.execute(
        sa.text(
            """
            UPDATE animal_lot_assignments
               SET kind = CASE
                     WHEN upper(regexp_replace(btrim(lote), '\\s+', ' ', 'g'))
                          IN ('LOTE 1', 'LOTE 2', 'LOTE 3')
                     THEN 'diet'
                     ELSE 'management'
                   END
            """
        )
    )

    op.alter_column("animal_lot_assignments", "kind", nullable=False)
    op.create_check_constraint(
        "ck_animal_lot_assignments_kind",
        "animal_lot_assignments",
        "kind IN ('diet', 'management')",
    )

    # A vigência passa a ser por tipo: um animal pode estar num lote de ordenha
    # e, ao mesmo tempo, num piquete. A baseline nunca traz os dois juntos, mas
    # o índice anterior impedia registrar a realidade da fazenda.
    op.drop_index(
        "uq_animal_lot_assignments_current", table_name="animal_lot_assignments"
    )
    op.create_index(
        "uq_animal_lot_assignments_current",
        "animal_lot_assignments",
        ["animal_id", "kind"],
        unique=True,
        postgresql_where=sa.text("valid_to IS NULL"),
    )


def downgrade() -> None:
    # Voltar ao índice antigo exige no máximo uma lotação vigente por animal.
    # Se houver animal com lote de ordenha e grupo de manejo ao mesmo tempo, a
    # reversão pararia aqui — melhor dizer isso do que escolher qual apagar.
    connection = op.get_bind()
    conflicting = connection.execute(
        sa.text(
            """
            SELECT count(*) FROM (
                SELECT animal_id FROM animal_lot_assignments
                 WHERE valid_to IS NULL
                 GROUP BY animal_id HAVING count(*) > 1
            ) AS overlapping
            """
        )
    ).scalar_one()
    if conflicting:
        raise RuntimeError(
            f"downgrade bloqueado: {conflicting} animais têm lote de ordenha e "
            "grupo de manejo vigentes ao mesmo tempo, o que o schema anterior "
            "não representa. Encerre uma das vigências antes de reverter."
        )

    op.drop_index(
        "uq_animal_lot_assignments_current", table_name="animal_lot_assignments"
    )
    op.create_index(
        "uq_animal_lot_assignments_current",
        "animal_lot_assignments",
        ["animal_id"],
        unique=True,
        postgresql_where=sa.text("valid_to IS NULL"),
    )
    op.drop_constraint(
        "ck_animal_lot_assignments_kind",
        "animal_lot_assignments",
        type_="check",
    )
    op.drop_column("animal_lot_assignments", "kind")
