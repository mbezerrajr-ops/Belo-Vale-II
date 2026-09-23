from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    LargeBinary,
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
    #: Preço pago por litro. Base do cálculo de receita no painel.
    milk_price_per_liter: Mapped[float | None] = mapped_column(Numeric(10, 4))
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
    #: Verdadeiro depois que um administrador redefine a senha: a conta só
    #: acessa a troca de senha até escolher uma nova.
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    #: Validade da senha provisória. Nula para senha escolhida pelo usuário.
    password_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
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
        CheckConstraint(
            "exit_reason IS NULL OR exit_reason IN "
            "('venda', 'morte', 'descarte', 'doacao', 'outro')",
            name="ck_animals_exit_reason",
        ),
        CheckConstraint(
            "(exited_on IS NULL) = (exit_reason IS NULL)",
            name="ck_animals_exit_complete",
        ),
        CheckConstraint(
            "(merged_into_id IS NULL) = (merged_at IS NULL)", name="ck_animals_merge_complete"
        ),
        CheckConstraint(
            "merged_into_id IS NULL OR merged_into_id <> id", name="ck_animals_merge_not_self"
        ),
        CheckConstraint(
            "merged_into_id IS NULL OR brinco IS NULL", name="ck_animals_merged_without_brinco"
        ),
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
    #: Baixa: data e motivo andam juntos (CHECK no banco). Nulos = no rebanho.
    exited_on: Mapped[date | None] = mapped_column(Date)
    exit_reason: Mapped[str | None] = mapped_column(String(16))
    exit_notes: Mapped[str | None] = mapped_column(Text)
    #: Ficha duplicada juntada a outra: aponta para a que ficou. Arquivada, fora
    #: do rebanho e das buscas, mas não apagada — as medições anuladas nela
    #: continuam sendo prova. Ver `app/services/animal_merge.py`.
    merged_into_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("animals.id", ondelete="RESTRICT", name="fk_animals_merged_into_id")
    )
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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

    `kind` separa duas coisas que a baseline mistura: o lote de ordenha, que
    tem dieta e custo, e o grupo de manejo, que é uma área ou categoria da
    fazenda. Ver `app/services/lot_kind.py`.
    """

    __tablename__ = "animal_lot_assignments"
    __table_args__ = (
        CheckConstraint(
            "source IN ('legacy_baseline', 'import', 'manual')",
            name="ck_animal_lot_assignments_source",
        ),
        CheckConstraint(
            "kind IN ('diet', 'management')",
            name="ck_animal_lot_assignments_kind",
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from",
            name="ck_animal_lot_assignments_period",
        ),
        # Uma vigência por tipo: o animal pode estar num lote de ordenha e,
        # ao mesmo tempo, num piquete.
        Index(
            "uq_animal_lot_assignments_current",
            "animal_id",
            "kind",
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
    #: `diet` = lote de ordenha, com dieta e custo. `management` = área ou
    #: categoria da fazenda, que diz onde o animal está.
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="diet")
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


class MediaAsset(TimestampedModel, Base):
    """Um arquivo enviado pelo app: foto da folha, gravação de voz, texto.

    Chamava-se `image_assets` enquanto só havia foto (migração 0013 renomeou).
    O conteúdo sempre foi genérico: hash, chave no armazenamento, tipo e
    tamanho — nada de largura, altura ou coisa de imagem.
    """

    __tablename__ = "media_assets"
    __table_args__ = (Index("uq_media_assets_farm_sha256", "farm_id", "sha256", unique=True),)

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    farm_id: Mapped[UUID] = mapped_column(ForeignKey("farms.id", ondelete="RESTRICT"), nullable=False)
    import_id: Mapped[UUID | None] = mapped_column(ForeignKey("imports.id", ondelete="SET NULL"))
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    object_key: Mapped[str | None] = mapped_column(String(512))
    media_type: Mapped[str | None] = mapped_column(String(128))
    byte_size: Mapped[int | None] = mapped_column(Integer)


#: Por que uma leitura falhou, para quem enviou saber o que fazer:
#: `reader_unavailable` (leitor fora do ar: o arquivo está bom, tente depois),
#: `unreadable` (o arquivo não tem o que ler: mande outro),
#: `sender_unknown` (ninguém responde pela leitura) e `internal` (o resto).
FAILURE_CODES = ("reader_unavailable", "unreadable", "sender_unknown", "internal")


class ExtractionRun(TimestampedModel, Base):
    __tablename__ = "extraction_runs"
    __table_args__ = (
        CheckConstraint(
            "failure_code IS NULL OR (status = 'failed' AND failure_code IN ("
            + ", ".join(f"'{code}'" for code in FAILURE_CODES)
            + "))",
            name="ck_extraction_runs_failure_code",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    media_asset_id: Mapped[UUID] = mapped_column(ForeignKey("media_assets.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", server_default=text("'pending'"), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(255))
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(32))


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
        CheckConstraint(
            "status IN ('active', 'superseded', 'voided')",
            name="ck_official_measurements_status",
        ),
        CheckConstraint(
            "provenance IN ('ocr_review', 'legacy_baseline', 'manual_entry', "
            "'file_import', 'proposal_review')",
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
            " OR"
            " (provenance = 'manual_entry'"
            "  AND entered_by_user_id IS NOT NULL"
            "  AND reviewed_by IS NOT NULL AND length(btrim(reviewed_by)) > 0)"
            " OR"
            " (provenance = 'file_import'"
            "  AND production_import_id IS NOT NULL"
            "  AND reviewed_by IS NOT NULL AND length(btrim(reviewed_by)) > 0)"
            " OR"
            " (provenance = 'proposal_review'"
            "  AND event_proposal_id IS NOT NULL"
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
    #: Anotação da pesagem para esta vaca ("→ Seca", "→ 3º Lote").
    observacao: Mapped[str | None] = mapped_column(String(200))
    reviewed_by: Mapped[str | None] = mapped_column(String(255))
    #: Quem lançou, quando a origem é `manual_entry`.
    entered_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    #: Medição que esta corrige, quando é uma correção.
    supersedes_measurement_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("official_measurements.id", ondelete="RESTRICT")
    )
    #: Importação de arquivo que criou esta leitura, quando é `file_import`.
    production_import_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("production_imports.id", ondelete="RESTRICT")
    )
    #: Proposta aprovada que criou esta leitura, quando é `proposal_review`.
    event_proposal_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("event_proposals.id", ondelete="RESTRICT")
    )


class ProductionImport(TimestampedModel, Base):
    """Um arquivo de coleta de leite enviado ao sistema.

    Imutável depois de gravado (trigger no banco): guarda o próprio arquivo,
    quem enviou, em que modo e o resumo do que foi feito. Cada leitura criada
    pela importação aponta para cá.
    """

    __tablename__ = "production_imports"
    __table_args__ = (
        CheckConstraint(
            "file_format IN ('csv', 'xlsx', 'pdf')", name="ck_production_imports_format"
        ),
        CheckConstraint(
            "mode IN ('new_only', 'replace')", name="ck_production_imports_mode"
        ),
        CheckConstraint(
            "mode <> 'replace' OR (reason IS NOT NULL AND length(btrim(reason)) >= 3)",
            name="ck_production_imports_replace_reason",
        ),
        CheckConstraint(
            "byte_size > 0 AND byte_size <= 5242880", name="ck_production_imports_size"
        ),
        Index(
            "uq_production_imports_same_file",
            "farm_id",
            "measured_on",
            "sha256",
            "mode",
            unique=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    farm_id: Mapped[UUID] = mapped_column(ForeignKey("farms.id", ondelete="RESTRICT"), nullable=False)
    measured_on: Mapped[date] = mapped_column(Date, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_format: Mapped[str] = mapped_column(String(8), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, deferred=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    imported_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class EventProposalSource(TimestampedModel, Base):
    """Um conteúdo lido por um leitor (foto, áudio, texto) e a saída bruta dele.

    Imutável (trigger no banco): é a prova do que foi lido.
    """

    __tablename__ = "event_proposal_sources"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('photo', 'audio', 'text')", name="ck_event_proposal_sources_kind"
        ),
        CheckConstraint(
            "(corrected_reference_date IS NULL AND corrected_by_user_id IS NULL AND corrected_at IS NULL)"
            " OR (corrected_reference_date IS NOT NULL AND corrected_by_user_id IS NOT NULL"
            " AND corrected_at IS NOT NULL)",
            name="ck_event_proposal_sources_correction",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    farm_id: Mapped[UUID] = mapped_column(ForeignKey("farms.id", ondelete="RESTRICT"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    extractor_name: Mapped[str] = mapped_column(String(64), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(64), nullable=False)
    reference_date: Mapped[date | None] = mapped_column(Date)
    raw_output: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    #: Data corrigida por quem revisa, quando o leitor errou a do cabeçalho.
    #: `reference_date` continua sendo a que foi lida.
    corrected_reference_date: Mapped[date | None] = mapped_column(Date)
    corrected_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: O arquivo de onde esta leitura saiu, quando veio pelo app: a foto da
    #: folha ou a gravação da ordenha. Quem revisa vê (ou ouve) ao lado do que
    #: foi lido.
    media_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL")
    )

    @property
    def effective_reference_date(self) -> date | None:
        return self.corrected_reference_date or self.reference_date


class EventProposal(TimestampedModel, Base):
    """Um evento lido, esperando decisão humana.

    `raw_fields` é o que o leitor entregou e nunca muda. `payload` é a
    interpretação inicial; `applied_payload` e `applied_animal_id` são o que a
    pessoa aprovou. Decidida, a proposta fica imutável (trigger no banco).
    """

    __tablename__ = "event_proposals"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('production', 'calving', 'dry_off', 'exit', 'lot_change', 'note')",
            name="ck_event_proposals_event_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')", name="ck_event_proposals_status"
        ),
        CheckConstraint(
            "status = 'pending' OR (decided_by_user_id IS NOT NULL AND decided_at IS NOT NULL)",
            name="ck_event_proposals_decided",
        ),
        CheckConstraint(
            "status <> 'rejected' OR "
            "(decision_reason IS NOT NULL AND length(btrim(decision_reason)) >= 3)",
            name="ck_event_proposals_rejection_reason",
        ),
        CheckConstraint(
            "status <> 'approved' OR "
            "(applied_animal_id IS NOT NULL AND applied_payload IS NOT NULL)",
            name="ck_event_proposals_applied",
        ),
        Index("ix_event_proposals_inbox", "farm_id", "status", "created_at"),
        Index("ix_event_proposals_source", "source_id", "position"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("event_proposal_sources.id", ondelete="RESTRICT"), nullable=False
    )
    farm_id: Mapped[UUID] = mapped_column(ForeignKey("farms.id", ondelete="RESTRICT"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    brinco_lido: Mapped[str | None] = mapped_column(String(64))
    nome_lido: Mapped[str | None] = mapped_column(String(255))
    candidate_animal_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("animals.id", ondelete="RESTRICT")
    )
    raw_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    confidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    alerts: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default=text("'pending'")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    decided_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    applied_animal_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("animals.id", ondelete="RESTRICT")
    )
    applied_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class Supply(TimestampedModel, Base):
    """Insumo da dieta.

    O custo de alimentação é o produto do preço por quilo pela dieta de cada
    lote — é assim que a fazenda controla o arraçoamento, e é o que torna o
    custo por vaca uma divisão do custo do lote.
    """

    __tablename__ = "supplies"
    __table_args__ = (
        CheckConstraint("price_per_kg >= 0", name="ck_supplies_price_positive"),
        Index("uq_supplies_farm_name", "farm_id", "name", unique=True),
        Index(
            "uq_supplies_farm_legacy_id",
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
    legacy_id: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    price_per_kg: Mapped[float] = mapped_column(Numeric(10, 5), nullable=False)
    prices: Mapped[list[SupplyPrice]] = relationship(back_populates="supply")
    diets: Mapped[list[SupplyDiet]] = relationship(back_populates="supply")


class SupplyPrice(TimestampedModel, Base):
    """Preço é evento temporal, como medição: um preço novo acrescenta ao
    histórico em vez de apagar o anterior."""

    __tablename__ = "supply_prices"
    __table_args__ = (
        CheckConstraint(
            "source IN ('legacy_baseline', 'manual')", name="ck_supply_prices_source"
        ),
        Index("uq_supply_prices_effective", "supply_id", "effective_on", unique=True),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    supply_id: Mapped[UUID] = mapped_column(
        ForeignKey("supplies.id", ondelete="CASCADE"), nullable=False
    )
    price_per_kg: Mapped[float] = mapped_column(Numeric(10, 5), nullable=False)
    effective_on: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    recorded_by: Mapped[str | None] = mapped_column(String(255))
    supply: Mapped[Supply] = relationship(back_populates="prices")


class SupplyDiet(TimestampedModel, Base):
    """Quilos por dia de um insumo, por lote."""

    __tablename__ = "supply_diets"
    __table_args__ = (
        CheckConstraint("kg_per_day >= 0", name="ck_supply_diets_positive"),
        Index("uq_supply_diets_lote", "supply_id", "lote", unique=True),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    supply_id: Mapped[UUID] = mapped_column(
        ForeignKey("supplies.id", ondelete="CASCADE"), nullable=False
    )
    lote: Mapped[str] = mapped_column(String(64), nullable=False)
    kg_per_day: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)
    supply: Mapped[Supply] = relationship(back_populates="diets")


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
