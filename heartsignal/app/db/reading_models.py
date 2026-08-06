"""Persistence models for the oracle Reading domain."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Persona(Base):
    """Versioned oracle persona available to the reading orchestrator."""

    __tablename__ = "personas"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Reading(Base):
    """Operational metadata for one private oracle reading."""

    __tablename__ = "readings"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','generating','preview_ready','full_ready','failed','deleted')",
            name="ck_readings_status",
        ),
        CheckConstraint(
            "access_level IN ('none','preview','full')",
            name="ck_readings_access_level",
        ),
        CheckConstraint("cost_units >= 0", name="ck_readings_cost_units"),
        CheckConstraint(
            "(status = 'full_ready' AND access_level = 'full' AND cost_units > 0 "
            "AND full_access_transaction_id IS NOT NULL) OR "
            "(status = 'deleted' AND access_level = 'none' AND "
            "((cost_units = 0 AND full_access_transaction_id IS NULL) OR "
            "(cost_units > 0 AND full_access_transaction_id IS NOT NULL))) OR "
            "(status NOT IN ('full_ready','deleted') AND cost_units = 0 "
            "AND full_access_transaction_id IS NULL)",
            name="ck_readings_paid_access",
        ),
        CheckConstraint(
            "(status IN ('draft','generating','failed','deleted') AND access_level = 'none') OR "
            "(status = 'preview_ready' AND access_level = 'preview') OR "
            "(status = 'full_ready' AND access_level = 'full')",
            name="ck_readings_status_access",
        ),
        CheckConstraint(
            "(status IN ('preview_ready','full_ready') AND generated_at IS NOT NULL "
            "AND failure_code IS NULL) OR "
            "(status = 'failed' AND generated_at IS NULL AND failure_code IS NOT NULL) OR "
            "(status IN ('draft','generating','deleted') AND generated_at IS NULL)",
            name="ck_readings_terminal_state",
        ),
        CheckConstraint(
            "status <> 'deleted' OR deleted_at IS NOT NULL",
            name="ck_readings_deleted_at",
        ),
        Index("ix_readings_user_created", "user_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    persona_id: Mapped[UUID] = mapped_column(
        ForeignKey("personas.id", ondelete="RESTRICT"), index=True
    )
    topic: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="draft", server_default="draft")
    access_level: Mapped[str] = mapped_column(String(16), default="none", server_default="none")
    cost_units: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    full_access_transaction_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "credit_transactions.id",
            ondelete="RESTRICT",
            use_alter=True,
            name="fk_readings_full_transaction",
        ),
        nullable=True,
    )
    engine_version: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(String(64))
    generation_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    persona: Mapped[Persona] = relationship()
    private_content: Mapped["ReadingPrivateContent | None"] = relationship(
        back_populates="reading", uselist=False, cascade="all, delete-orphan"
    )
    symbols: Mapped[list["ReadingSymbol"]] = relationship(
        back_populates="reading",
        cascade="all, delete-orphan",
        order_by="ReadingSymbol.ordinal",
    )


class ReadingPrivateContent(Base):
    """Authenticated ciphertext separated from operational reading metadata."""

    __tablename__ = "reading_private_content"

    reading_id: Mapped[UUID] = mapped_column(
        ForeignKey("readings.id", ondelete="CASCADE"), primary_key=True
    )
    question_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    context_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    result_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    question_format_version: Mapped[int | None] = mapped_column(Integer)
    context_format_version: Mapped[int | None] = mapped_column(Integer)
    result_format_version: Mapped[int | None] = mapped_column(Integer)
    content_delete_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    content_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    reading: Mapped[Reading] = relationship(back_populates="private_content")


class ReadingSymbol(Base):
    """Deterministically selected symbol attached to a reading."""

    __tablename__ = "reading_symbols"
    __table_args__ = (
        CheckConstraint("ordinal >= 0", name="ck_reading_symbols_ordinal"),
        CheckConstraint(
            "orientation IN ('upright','reversed','neutral')",
            name="ck_reading_symbols_orientation",
        ),
        UniqueConstraint("reading_id", "ordinal", name="uq_reading_symbols_ordinal"),
        UniqueConstraint("reading_id", "position", name="uq_reading_symbols_position"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    reading_id: Mapped[UUID] = mapped_column(
        ForeignKey("readings.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    symbol_id: Mapped[str] = mapped_column(String(64))
    position: Mapped[str] = mapped_column(String(64))
    orientation: Mapped[str] = mapped_column(String(16), default="neutral")
    catalog_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reading: Mapped[Reading] = relationship(back_populates="symbols")
