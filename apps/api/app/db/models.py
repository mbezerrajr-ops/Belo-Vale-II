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
    __tablename__ = "animals"
    __table_args__ = (Index("uq_animals_farm_identifier", "farm_id", "identifier", unique=True),)

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    farm_id: Mapped[UUID] = mapped_column(ForeignKey("farms.id", ondelete="RESTRICT"), nullable=False)
    identifier: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    farm: Mapped[Farm] = relationship(back_populates="animals")


class Import(TimestampedModel, Base):
    __tablename__ = "imports"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    farm_id: Mapped[UUID] = mapped_column(ForeignKey("farms.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", server_default=text("'pending'"), nullable=False)
    source: Mapped[str | None] = mapped_column(String(255))
    initiated_by: Mapped[str | None] = mapped_column(String(255))


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
            "status <> 'active' OR (review_decision_id IS NOT NULL AND reviewed_by IS NOT NULL AND length(btrim(reviewed_by)) > 0)",
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
    measured_on: Mapped[date] = mapped_column(Date, nullable=False)
    values: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(255))


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
