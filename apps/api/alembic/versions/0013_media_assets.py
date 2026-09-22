"""image_assets vira media_assets: o que entra pelo app não é só foto.

A fase 3 traz a gravação de voz pela mesma porta do envio de foto — mesmo
armazenamento, mesma fila, mesma caixa de Revisão. Guardar um áudio numa
tabela chamada "imagens" deixaria o esquema mentindo para sempre, e a fase
seguinte (texto) herdaria a mentira.

Em PostgreSQL, renomear tabela, coluna e índice é metadado puro: nenhuma
linha é reescrita, e as chaves estrangeiras, os índices e os gatilhos
continuam valendo. Os gatilhos de 0010 e 0011 não citam estas colunas pelo
nome — `forbid_event_proposal_source_update` compara a linha inteira em
JSONB menos as colunas de correção de data —, então nada neles precisa mudar.

Revision ID: 0013_media_assets
Revises: 0012_source_photo
"""

from __future__ import annotations

from alembic import op

revision = "0013_media_assets"
down_revision = "0012_source_photo"
branch_labels = None
depends_on = None


#: Os nomes que o Postgres cria sozinho (chave primária e estrangeiras) não
#: acompanham o renome da tabela, e continuariam dizendo "image".
_CONSTRAINTS = (
    ("image_assets_pkey", "media_assets_pkey"),
    ("image_assets_farm_id_fkey", "media_assets_farm_id_fkey"),
    ("image_assets_import_id_fkey", "media_assets_import_id_fkey"),
    ("extraction_runs_image_asset_id_fkey", "extraction_runs_media_asset_id_fkey"),
    ("event_proposal_sources_image_asset_id_fkey", "event_proposal_sources_media_asset_id_fkey"),
)

_TABELA = {
    "image_assets_pkey": "media_assets",
    "image_assets_farm_id_fkey": "media_assets",
    "image_assets_import_id_fkey": "media_assets",
    "extraction_runs_image_asset_id_fkey": "extraction_runs",
    "event_proposal_sources_image_asset_id_fkey": "event_proposal_sources",
}


def upgrade() -> None:
    op.alter_column("extraction_runs", "image_asset_id", new_column_name="media_asset_id")
    op.alter_column("event_proposal_sources", "image_asset_id", new_column_name="media_asset_id")
    op.execute("ALTER INDEX uq_image_assets_farm_sha256 RENAME TO uq_media_assets_farm_sha256")
    op.rename_table("image_assets", "media_assets")
    # Os nomes que o Postgres deu sozinho continuariam dizendo "image".
    for antigo, atual in _CONSTRAINTS:
        op.execute(f"ALTER TABLE {_TABELA[antigo]} RENAME CONSTRAINT {antigo} TO {atual}")


def downgrade() -> None:
    for antigo, atual in _CONSTRAINTS:
        op.execute(f"ALTER TABLE {_TABELA[antigo]} RENAME CONSTRAINT {atual} TO {antigo}")
    op.rename_table("media_assets", "image_assets")
    op.execute("ALTER INDEX uq_media_assets_farm_sha256 RENAME TO uq_image_assets_farm_sha256")
    op.alter_column("event_proposal_sources", "media_asset_id", new_column_name="image_asset_id")
    op.alter_column("extraction_runs", "media_asset_id", new_column_name="image_asset_id")
