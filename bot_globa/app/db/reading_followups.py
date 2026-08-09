"""Durable, encrypted entitlement for the one follow-up included with a paid reading.

Keyed on `reading_id`, so every persona gets the same entitlement: the reading is what
was paid for, regardless of which use case produced it.
"""

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
    Table,
    UniqueConstraint,
    event,
    func,
    text,
)
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReadingFollowUp(Base):
    """One claim-fenced follow-up entitlement per paid full-access reading."""

    __tablename__ = "reading_followups"
    __table_args__ = (
        UniqueConstraint("reading_id", name="uq_reading_followups_reading"),
        CheckConstraint(
            "status IN ('available','reserved','completed')",
            name="ck_reading_followups_status",
        ),
        CheckConstraint(
            "reservation_count >= 0 AND llm_attempt_count >= 0",
            name="ck_reading_followups_attempts",
        ),
        CheckConstraint(
            "(status = 'available' AND claim_id IS NULL AND lease_until IS NULL "
            "AND question_ciphertext IS NULL AND answer_ciphertext IS NULL "
            "AND completed_at IS NULL) OR "
            "(status = 'reserved' AND claim_id IS NOT NULL AND lease_until IS NOT NULL "
            "AND question_ciphertext IS NOT NULL AND answer_ciphertext IS NULL "
            "AND completed_at IS NULL) OR "
            "(status = 'completed' AND claim_id IS NULL AND lease_until IS NULL "
            "AND question_ciphertext IS NOT NULL AND answer_ciphertext IS NOT NULL "
            "AND completed_at IS NOT NULL)",
            name="ck_reading_followups_state",
        ),
        Index(
            "ix_reading_followups_expired_reservations",
            "lease_until",
            postgresql_where=text("status = 'reserved'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    reading_id: Mapped[UUID] = mapped_column(
        ForeignKey("readings.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="available", server_default="available")
    claim_id: Mapped[UUID | None] = mapped_column(nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    question_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    answer_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    prompt_version: Mapped[str] = mapped_column(String(64), default="reading-followup-v1")
    reservation_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    llm_attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    llm_provider: Mapped[str | None] = mapped_column(String(32))
    model_name: Mapped[str | None] = mapped_column(String(255))
    provider_request_id: Mapped[str | None] = mapped_column(String(255))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    last_failure_code: Mapped[str | None] = mapped_column(String(64))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


def _create_purge_trigger(_: Table, connection: Connection, **__: object) -> None:
    """Soft-deleting a reading must take its follow-up ciphertext with it."""
    connection.exec_driver_sql(
        """
        CREATE OR REPLACE FUNCTION purge_reading_followup_on_delete()
        RETURNS trigger AS $$
        BEGIN
          IF NEW.status = 'deleted' AND OLD.status IS DISTINCT FROM 'deleted' THEN
            DELETE FROM reading_followups WHERE reading_id = NEW.id;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    connection.exec_driver_sql(
        "DROP TRIGGER IF EXISTS trg_purge_reading_followup_on_delete ON readings"
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER trg_purge_reading_followup_on_delete
        AFTER UPDATE OF status ON readings
        FOR EACH ROW EXECUTE FUNCTION purge_reading_followup_on_delete()
        """
    )


def _drop_purge_trigger(_: Table, connection: Connection, **__: object) -> None:
    connection.exec_driver_sql(
        "DROP TRIGGER IF EXISTS trg_purge_reading_followup_on_delete ON readings"
    )
    connection.exec_driver_sql("DROP FUNCTION IF EXISTS purge_reading_followup_on_delete()")


event.listen(ReadingFollowUp.__table__, "after_create", _create_purge_trigger)
event.listen(ReadingFollowUp.__table__, "before_drop", _drop_purge_trigger)
