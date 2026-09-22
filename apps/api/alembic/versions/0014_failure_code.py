"""A leitura que falha guarda o motivo.

Até aqui, uma leitura com defeito ficava só `failed`, e quem enviou não tinha
como saber — o aviso "as propostas aparecem aqui quando terminar" continuava
na tela. Os remédios são diferentes: gravação sem fala se resolve gravando de
novo, ainda com as vacas no curral; leitor desligado, não — o arquivo está
guardado, e ler de novo depois resolve.

Coluna nova, anulável e sem valor padrão: em PostgreSQL é metadado puro,
nenhuma linha é reescrita. Leituras antigas que falharam ficam sem motivo, e
a API responde "internal" para elas.

Revision ID: 0014_failure_code
Revises: 0013_media_assets
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_failure_code"
down_revision = "0013_media_assets"
branch_labels = None
depends_on = None

#: Copiado de propósito, e não importado de `app.db.models`: a migração
#: descreve o esquema como ele era neste ponto, mesmo que a lista mude depois.
_CODES = ("reader_unavailable", "unreadable", "sender_unknown", "internal")


def upgrade() -> None:
    op.add_column("extraction_runs", sa.Column("failure_code", sa.String(32), nullable=True))
    op.create_check_constraint(
        "ck_extraction_runs_failure_code",
        "extraction_runs",
        "failure_code IS NULL OR (status = 'failed' AND failure_code IN ("
        + ", ".join(f"'{code}'" for code in _CODES)
        + "))",
    )


def downgrade() -> None:
    op.drop_constraint("ck_extraction_runs_failure_code", "extraction_runs", type_="check")
    op.drop_column("extraction_runs", "failure_code")
