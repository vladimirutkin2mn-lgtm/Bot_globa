"""Persistence models for explicit-consent oracle memory."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
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

_MEMORY_KINDS = (
    "user_statement",
    "user_preference",
    "personal_goal",
    "relationship_notes",
    "recurring_theme",
    "birth_profile",
    "oracle_preference",
)
_MEMORY_CLAIM_BASES = ("user_stated", "model_inferred")
_MEMORY_SOURCE_TYPES = ("user_explicit", "reading_derived", "profile_imported")
_MEMORY_EXTRACTION_JOB_STATUSES = (
    "pending",
    "claimed",
    "completed",
    "skipped_no_consent",
    "skipped_source_unavailable",
    "failed",
)


class OracleMemoryConsent(Base):
    """Current explicit memory consent, independent from onboarding consent."""

    __tablename__ = "oracle_memory_consents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('granted','revoked')",
            name="ck_oracle_memory_consents_status",
        ),
        CheckConstraint(
            "(status = 'granted' AND accepted_at IS NOT NULL AND revoked_at IS NULL) OR "
            "(status = 'revoked' AND revoked_at IS NOT NULL)",
            name="ck_oracle_memory_consents_state",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(16))
    consent_version: Mapped[str] = mapped_column(String(64))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class OracleMemoryItem(Base):
    """Non-secret metadata for one consented memory item."""

    __tablename__ = "oracle_memory_items"
    __table_args__ = (
        CheckConstraint(
            "kind IN (" + ",".join(f"'{value}'" for value in _MEMORY_KINDS) + ")",
            name="ck_oracle_memory_items_kind",
        ),
        CheckConstraint(
            "status IN ('active','deleted')",
            name="ck_oracle_memory_items_status",
        ),
        CheckConstraint(
            "confidence_milli BETWEEN 1 AND 1000",
            name="ck_oracle_memory_items_confidence",
        ),
        CheckConstraint(
            "claim_basis IN (" + ",".join(f"'{value}'" for value in _MEMORY_CLAIM_BASES) + ")",
            name="ck_oracle_memory_items_claim_basis",
        ),
        CheckConstraint(
            "source_type IN (" + ",".join(f"'{value}'" for value in _MEMORY_SOURCE_TYPES) + ")",
            name="ck_oracle_memory_items_source_type",
        ),
        CheckConstraint(
            "(source_type = 'reading_derived' AND candidate_key IS NOT NULL) OR "
            "(source_type <> 'reading_derived' AND source_reading_id IS NULL "
            "AND candidate_key IS NULL)",
            name="ck_oracle_memory_items_provenance",
        ),
        CheckConstraint(
            "(status = 'active' AND deleted_at IS NULL) OR "
            "(status = 'deleted' AND deleted_at IS NOT NULL)",
            name="ck_oracle_memory_items_state",
        ),
        Index("ix_oracle_memory_items_user_status_created", "user_id", "status", "created_at"),
        Index(
            "ix_oracle_memory_items_extraction_lookup",
            "user_id",
            "source_reading_id",
            "extraction_version",
            "candidate_key",
            "status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    confidence_milli: Mapped[int] = mapped_column(Integer)
    claim_basis: Mapped[str] = mapped_column(
        String(24), default="user_stated", server_default="user_stated"
    )
    source_type: Mapped[str] = mapped_column(String(32))
    source_reading_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("readings.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_persona_code: Mapped[str | None] = mapped_column(String(64))
    extraction_version: Mapped[str] = mapped_column(String(64))
    candidate_key: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    private_content: Mapped["OracleMemoryPrivateContent | None"] = relationship(
        back_populates="item",
        uselist=False,
        cascade="all, delete-orphan",
    )


class OracleMemoryPrivateContent(Base):
    """Authenticated ciphertext kept outside operational memory metadata."""

    __tablename__ = "oracle_memory_private_content"
    __table_args__ = (
        CheckConstraint(
            "(value_ciphertext IS NOT NULL AND value_format_version IS NOT NULL "
            "AND value_format_version > 0 AND content_deleted_at IS NULL) OR "
            "(value_ciphertext IS NULL AND value_format_version IS NULL "
            "AND content_deleted_at IS NOT NULL)",
            name="ck_oracle_memory_private_content_state",
        ),
    )

    memory_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("oracle_memory_items.id", ondelete="CASCADE"), primary_key=True
    )
    value_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    value_format_version: Mapped[int | None] = mapped_column(Integer)
    content_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    item: Mapped[OracleMemoryItem] = relationship(back_populates="private_content")


class ReadingMemoryExtractionJob(Base):
    """Lease-based background extraction trigger containing no private reading text."""

    __tablename__ = "reading_memory_extraction_jobs"
    __table_args__ = (
        UniqueConstraint(
            "reading_id",
            "extraction_version",
            name="uq_reading_memory_extraction_job_version",
        ),
        CheckConstraint(
            "status IN ("
            + ",".join(f"'{value}'" for value in _MEMORY_EXTRACTION_JOB_STATUSES)
            + ")",
            name="ck_reading_memory_extraction_jobs_status",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_reading_memory_extraction_jobs_attempt_count",
        ),
        CheckConstraint(
            "(status = 'pending' AND claim_id IS NULL AND claimed_by IS NULL "
            "AND claimed_at IS NULL AND lease_until IS NULL AND completed_at IS NULL) OR "
            "(status = 'claimed' AND claim_id IS NOT NULL AND claimed_by IS NOT NULL "
            "AND claimed_at IS NOT NULL AND lease_until IS NOT NULL AND completed_at IS NULL) OR "
            "(status IN ('completed','skipped_no_consent','skipped_source_unavailable','failed') "
            "AND claim_id IS NULL AND lease_until IS NULL AND completed_at IS NOT NULL)",
            name="ck_reading_memory_extraction_jobs_state",
        ),
        Index(
            "ix_reading_memory_extraction_jobs_due",
            "status",
            "available_at",
            "lease_until",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    reading_id: Mapped[UUID] = mapped_column(
        ForeignKey("readings.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    extraction_version: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="pending", server_default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    claim_id: Mapped[UUID | None] = mapped_column(nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(String(255))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
