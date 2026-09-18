from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Boolean,
    Date,
    DateTime,
    FetchedValue,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TimestampedModel:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
        server_onupdate=FetchedValue(),
        nullable=False,
    )


class Farm(TimestampedModel, Base):
    __tablename__ = "farms"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str | None] = mapped_column(String(64), unique=True)
    animals: Mapped[list[Animal]] = relationship(back_populates="farm")


class User(TimestampedModel, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('operator', 'reviewer', 'admin')", name="ck_users_role"
        ),
        Index("uq_users_email_lower", text("lower(email)"), unique=True),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )


class Animal(TimestampedModel, Base):
    """Cadastro do animal.

    Três identificadores com papéis distintos, deliberadamente separados:

    - ``id``: identidade interna, imutável, nunca reaproveitada;
    - ``brinco``: chave de *matching automático* de arquivos novos. Nulo é um
      estado válido — 142 registros da baseline não têm brinco legível — e
      significa apenas que o animal não recebe associação automática, nunca
      que o cadastro é inválido;
    - ``legacy_id``: chave de *migração* e reconciliação com a baseline legada.

    ``numero_legado`` é informativo e deliberadamente **não** tem índice único:
    colide em três casos reais da baseline e não é identidade.
    """

    __tablename__ = "animals"
    __table_args__ = (
        Index("uq_animals_farm_identifier", "farm_id", "identifier", unique=True),
        Index(
            "uq_animals_farm_brinco",
            "farm_id",
            "brinco",
            unique=True,
            postgresql_where=text("brinco IS NOT NULL"),
        ),
        Index(
            "uq_animals_farm_legacy_id",
            "farm_id",
            "legacy_id",
            unique=True,
            postgresql_where=text("legacy_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    farm_id: Mapped[UUID] = mapped_column(ForeignKey("farms.id", ondelete="RESTRICT"), nullable=False)
    identifier: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    brinco: Mapped[str | None] = mapped_column(String(64))
    brinco_origem: Mapped[str | None] = mapped_column(String(64))
    legacy_id: Mapped[str | None] = mapped_column(String(64))
    numero_legado: Mapped[str | None] = mapped_column(String(64))
    situacao: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str | None] = mapped_column(String(32))
    ultimo_parto: Mapped[date | None] = mapped_column(Date)
    nascimento: Mapped[date | None] = mapped_column(Date)
    peso: Mapped[float | None] = mapped_column(Numeric(6, 2))
    observacoes: Mapped[str | None] = mapped_column(Text)
    farm: Mapped[Farm] = relationship(back_populates="animals")
    lot_assignments: Mapped[list[AnimalLotAssignment]] = relationship(
        back_populates="animal"
    )


class AnimalLotAssignment(TimestampedModel, Base):
    """Histórico de lotação.

    A vaca muda de lote, e lote não é parte da identidade. Um lote novo não
    sobrescreve o anterior: encerra a vigência do anterior e abre uma nova
    linha, de modo que relatórios históricos não sejam reinterpretados com o
    lote de hoje.
    """

    __tablename__ = "animal_lot_assignments"
    __table_args__ = (
        CheckConstraint(
            "source IN ('legacy_baseline', 'import', 'manual')",
            name="ck_animal_lot_assignments_source",
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from",
            name="ck_animal_lot_assignments_period",
        ),
        Index(
            "uq_animal_lot_assignments_current",
            "animal_id",
            unique=True,
            postgresql_where=text("valid_to IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    animal_id: Mapped[UUID] = mapped_column(
        ForeignKey("animals.id", ondelete="CASCADE"), nullable=False
    )
    lote: Mapped[str] = mapped_column(String(64), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_import_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("imports.id", ondelete="SET NULL")
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(255))
    animal: Mapped[Animal] = relationship(back_populates="lot_assignments")


class BaselineImport(TimestampedModel, Base):
    """Importação administrativa da baseline legada.

    Existe para que uma medição histórica possa declarar honestamente de onde
    veio, em vez de fabricar uma revisão de OCR que nunca aconteceu. O
    ``source_sha256`` torna a migração verificável depois: dá para provar qual
    versão exata do arquivo originou cada medição.
    """

    __tablename__ = "baseline_imports"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    farm_id: Mapped[UUID] = mapped_column(ForeignKey("farms.id", ondelete="RESTRICT"), nullable=False)
    source_path: Mapped[str] = mapped_column(String(512), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    animal_count: Mapped[int] = mapped_column(Integer, nullable=False)
    measurement_count: Mapped[int] = mapped_column(Integer, nullable=False)
    approved_by: Mapped[str] = mapped_column(String(255), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)


class Import(TimestampedModel, Base):
    __tablename__ = "imports"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    farm_id: Mapped[UUID] = mapped_column(ForeignKey("farms.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", server_default=text("'pending'"), nullable=False)
    source: Mapped[str | None] = mapped_column(String(255))
    initiated_by: Mapped[str | None] = mapped_column(String(255))
    declared_lot: Mapped[str | None] = mapped_column(String(64))
    declared_measured_on: Mapped[date | None] = mapped_column(Date)


class ImageAsset(TimestampedModel, Base):
    __tablename__ = "image_assets"
    __table_args__ = (Index("uq_image_assets_farm_sha256", "farm_id", "sha256", unique=True),)

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    farm_id: Mapped[UUID] = mapped_column(ForeignKey("farms.id", ondelete="RESTRICT"), nullable=False)
    import_id: Mapped[UUID | None] = mapped_column(ForeignKey("imports.id", ondelete="SET NULL"))
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    object_key: Mapped[str | None] = mapped_column(String(512))
    media_type: Mapped[str | None] = mapped_column(String(128))
    byte_size: Mapped[int | None] = mapped_column(Integer)


class ExtractionRun(TimestampedModel, Base):
    __tablename__ = "extraction_runs"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    image_asset_id: Mapped[UUID] = mapped_column(ForeignKey("image_assets.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", server_default=text("'pending'"), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(255))
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExtractedLine(TimestampedModel, Base):
    __tablename__ = "extracted_lines"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    extraction_run_id: Mapped[UUID] = mapped_column(ForeignKey("extraction_runs.id", ondelete="RESTRICT"), nullable=False)
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_values: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    normalized_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    confidence: Mapped[float | None] = mapped_column(Float)
    crop_coordinates: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"), nullable=False)
    candidate_animal_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("animals.id", ondelete="SET NULL")
    )


class ValidationAlert(TimestampedModel, Base):
    __tablename__ = "validation_alerts"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    extracted_line_id: Mapped[UUID] = mapped_column(ForeignKey("extracted_lines.id", ondelete="RESTRICT"), nullable=False)
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class ReviewDecision(TimestampedModel, Base):
    __tablename__ = "review_decisions"
    __table_args__ = (
        CheckConstraint("decision IN ('approved', 'rejected')", name="ck_review_decisions_decision"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    extracted_line_id: Mapped[UUID] = mapped_column(ForeignKey("extracted_lines.id", ondelete="RESTRICT"), nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    corrected_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(Text)
    expected_version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"), nullable=False)


class OfficialMeasurement(TimestampedModel, Base):
    __tablename__ = "official_measurements"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'superseded')", name="ck_official_measurements_status"),
        CheckConstraint(
            "provenance IN ('ocr_review', 'legacy_baseline')",
            name="ck_official_measurements_provenance",
        ),
        # Toda medição ativa continua obrigada a ter proveniência rastreável e
        # um responsável. O que muda em relação à versão anterior é que o
        # sistema deixa de exigir uma revisão de OCR para dados que nunca
        # passaram por OCR: uma medição da baseline declara que veio da
        # baseline, em vez de fabricar uma ReviewDecision inexistente.
        CheckConstraint(
            "status <> 'active' OR ("
            " (provenance = 'ocr_review'"
            "  AND review_decision_id IS NOT NULL"
            "  AND reviewed_by IS NOT NULL AND length(btrim(reviewed_by)) > 0)"
            " OR"
            " (provenance = 'legacy_baseline'"
            "  AND baseline_import_id IS NOT NULL"
            "  AND reviewed_by IS NOT NULL AND length(btrim(reviewed_by)) > 0)"
            ")",
            name="ck_official_measurements_active_review_provenance",
        ),
        Index(
            "uq_official_measurements_active_animal_measured_on",
            "animal_id",
            "measured_on",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    animal_id: Mapped[UUID] = mapped_column(ForeignKey("animals.id", ondelete="RESTRICT"), nullable=False)
    extracted_line_id: Mapped[UUID | None] = mapped_column(ForeignKey("extracted_lines.id", ondelete="SET NULL"))
    review_decision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("review_decisions.id", ondelete="RESTRICT")
    )
    baseline_import_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("baseline_imports.id", ondelete="RESTRICT")
    )
    measured_on: Mapped[date] = mapped_column(Date, nullable=False)
    values: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    provenance: Mapped[str] = mapped_column(
        String(32), default="ocr_review", server_default=text("'ocr_review'"), nullable=False
    )
    lote_observado: Mapped[str | None] = mapped_column(String(64))
    reviewed_by: Mapped[str | None] = mapped_column(String(255))


class RefreshToken(TimestampedModel, Base):
    """Sessão longa, revogável.

    O token de acesso é curto de propósito; este é o que permite ao usuário
    continuar trabalhando sem refazer login a cada quinze minutos. Como ele
    vale por muito tempo, precisa ser revogável — e por isso vive no banco, ao
    contrário do token de acesso, que é autocontido.

    Guarda-se apenas o hash: quem obtiver leitura do banco não consegue assumir
    a sessão de ninguém.
    """

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        Index("uq_refresh_tokens_hash", "token_hash", unique=True),
        Index("ix_refresh_tokens_user", "user_id"),
        Index("ix_refresh_tokens_family", "family_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Tokens gerados por rotação de uma mesma sessão compartilham a família,
    #: para que detectar reuso permita derrubar a sessão inteira.
    family_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(String(64))


class AuditEvent(TimestampedModel, Base):
    __tablename__ = "audit_events"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    farm_id: Mapped[UUID | None] = mapped_column(ForeignKey("farms.id", ondelete="SET NULL"))
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    previous_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    new_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
