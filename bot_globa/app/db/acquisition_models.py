"""First-touch acquisition attribution kept separate from the user profile."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserAcquisitionAttribution(Base):
    __tablename__ = "user_acquisition_attributions"
    __table_args__ = (
        CheckConstraint(
            "referral_token ~ '^[0-9a-f]{16}$'",
            name="ck_user_acquisition_attributions_referral_token",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    referral_token: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    attributed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
