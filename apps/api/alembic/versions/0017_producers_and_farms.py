"""Contas produtoras, vínculos e migração preservadora da operação existente."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0017_producers_and_farms"
down_revision = "0016_measurement_note"
branch_labels = depends_on = None


def timestamps():
    return [
        sa.Column(
            name,
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        )
        for name in ("created_at", "updated_at")
    ]


def upgrade():
    op.create_table(
        "producer_accounts",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "storage_limit_bytes",
            sa.BigInteger,
            nullable=False,
            server_default="1000000000",
        ),
        sa.Column(
            "daily_reading_limit", sa.Integer, nullable=False, server_default="100"
        ),
        *timestamps(),
        sa.CheckConstraint(
            "storage_limit_bytes > 0 AND daily_reading_limit > 0",
            name="ck_producer_limits",
        ),
    )
    op.add_column(
        "farms",
        sa.Column(
            "producer_account_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("producer_accounts.id", ondelete="RESTRICT"),
        ),
    )
    op.create_index("ix_farms_producer_account_id", "farms", ["producer_account_id"])
    op.add_column(
        "farms",
        sa.Column(
            "timezone", sa.String(64), nullable=False, server_default="America/Recife"
        ),
    )
    op.add_column(
        "farms",
        sa.Column(
            "lot_settings",
            pg.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True)))
    op.add_column(
        "users",
        sa.Column(
            "email_verification_required",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "is_platform_admin", sa.Boolean, nullable=False, server_default=sa.false()
        ),
    )
    op.create_table(
        "producer_memberships",
        sa.Column(
            "producer_account_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("producer_accounts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "role IN ('owner', 'admin')", name="ck_producer_membership_role"
        ),
    )
    op.create_table(
        "farm_memberships",
        sa.Column(
            "farm_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("farms.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        *timestamps(),
        sa.CheckConstraint(
            "role IN ('operator', 'reviewer', 'admin')", name="ck_farm_membership_role"
        ),
    )
    op.create_index(
        "uq_producer_single_owner",
        "producer_memberships",
        ["producer_account_id"],
        unique=True,
        postgresql_where=sa.text("role='owner'"),
    )
    op.create_table(
        "account_tokens",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
        ),
        sa.Column(
            "farm_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("farms.id", ondelete="CASCADE"),
        ),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("role", sa.String(16)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        *timestamps(),
    )
    # A autorização antiga só fazia sentido com uma fazenda. Recusar qualquer
    # ambiguidade em vez de distribuir acesso a dados de produtores distintos.
    op.execute("""
    DO $$ DECLARE account_id uuid; owner_id uuid;
    BEGIN
      IF (SELECT count(*) FROM farms) > 1 THEN
        RAISE EXCEPTION 'múltiplas fazendas legadas: classifique os proprietários antes da migração';
      END IF;
      IF EXISTS (SELECT 1 FROM farms) THEN
        SELECT id INTO owner_id FROM users WHERE role='admin' AND is_active ORDER BY created_at, id LIMIT 1;
        IF owner_id IS NULL THEN RAISE EXCEPTION 'defina um administrador ativo antes da migração'; END IF;
        INSERT INTO producer_accounts(name) SELECT name FROM farms RETURNING id INTO account_id;
        UPDATE farms SET producer_account_id=account_id,
          lot_settings='[{"name":"LOTE 1","kind":"diet"},{"name":"LOTE 2","kind":"diet"},{"name":"LOTE 3","kind":"diet"},{"name":"PRÉ-PARTO","kind":"management"},{"name":"PIQUETES / REPASSE","kind":"management"},{"name":"ENGORDA","kind":"management"},{"name":"ENGENHO","kind":"management"},{"name":"INSERLEITE","kind":"management"},{"name":"BEZERREIRO","kind":"management"},{"name":"CAJARANAS","kind":"management"},{"name":"PALMA","kind":"management"},{"name":"COLÉGIO","kind":"management"},{"name":"ABREU","kind":"management"}]'::jsonb;
        INSERT INTO producer_memberships(producer_account_id,user_id,role) VALUES(account_id,owner_id,'owner');
        INSERT INTO farm_memberships(farm_id,user_id,role,is_active) SELECT f.id,u.id,u.role,u.is_active FROM farms f CROSS JOIN users u;
        UPDATE users SET email_verified_at=CURRENT_TIMESTAMP;
      END IF;
    END $$;
    """)


def downgrade():
    # Não transformar uma instalação com vários clientes numa operação global.
    op.execute("""DO $$ BEGIN
      IF (SELECT count(*) FROM producer_accounts)>1 OR (SELECT count(*) FROM farms)>1 THEN
        RAISE EXCEPTION 'downgrade recusado: há vários produtores ou fazendas';
      END IF;
    END $$;""")
    op.drop_table("account_tokens")
    op.drop_table("farm_memberships")
    op.drop_table("producer_memberships")
    op.drop_column("users", "is_platform_admin")
    op.drop_column("users", "email_verified_at")
    op.drop_column("users", "email_verification_required")
    op.drop_column("farms", "lot_settings")
    op.drop_column("farms", "timezone")
    op.drop_index("ix_farms_producer_account_id", "farms")
    op.drop_column("farms", "producer_account_id")
    op.drop_table("producer_accounts")
