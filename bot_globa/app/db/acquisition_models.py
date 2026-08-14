"""Minimal first-touch acquisition attribution persisted for growth measurement."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AcquisitionAttribution(Base):
    """Immutable first-touch attribution for one Oracle user.

    The primary key on ``user_id`` deliberately permits only one first-touch row.
    Campaign query strings and provider secrets are not stored here.
    """

    __tablename__ = "acquisition_attributions"
    __table_args__ = (
        CheckConstraint("source = 'partizan'", name="ck_acquisition_attributions_source"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    source: Mapped[str] = mapped_column(
        String(16), default="partizan", server_default="partizan"
    )
    experiment_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
