"""Persistence models for explicit-consent encrypted birth profiles."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class BirthProfileConsent(Base):
    """Independent explicit consent for storing and reusing birth details."""

    __tablename__ = "birth_profile_consents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('granted','revoked')",
            name="ck_birth_profile_consents_status",
        ),
        CheckConstraint(
            "(status = 'granted' AND accepted_at IS NOT NULL AND revoked_at IS NULL) OR "
            "(status = 'revoked' AND revoked_at IS NOT NULL)",
            name="ck_birth_profile_consents_state",
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


class BirthProfile(Base):
    """Non-secret lifecycle metadata for one reusable birth profile."""

    __tablename__ = "birth_profiles"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active','deleted')",
            name="ck_birth_profiles_status",
        ),
        CheckConstraint(
            "(status = 'active' AND deleted_at IS NULL) OR "
            "(status = 'deleted' AND deleted_at IS NOT NULL)",
            name="ck_birth_profiles_state",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    profile_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    private_content: Mapped["BirthProfilePrivateContent | None"] = relationship(
        back_populates="profile",
        uselist=False,
        cascade="all, delete-orphan",
    )


class BirthProfilePrivateContent(Base):
    """Authenticated ciphertext containing date, time, place and timezone."""

    __tablename__ = "birth_profile_private_content"
    __table_args__ = (
        CheckConstraint(
            "(payload_ciphertext IS NOT NULL AND payload_format_version IS NOT NULL "
            "AND payload_format_version > 0 AND content_deleted_at IS NULL) OR "
            "(payload_ciphertext IS NULL AND payload_format_version IS NULL "
            "AND content_deleted_at IS NOT NULL)",
            name="ck_birth_profile_private_content_state",
        ),
    )

    birth_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("birth_profiles.id", ondelete="CASCADE"), primary_key=True
    )
    payload_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    payload_format_version: Mapped[int | None] = mapped_column(Integer)
    content_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    profile: Mapped[BirthProfile] = relationship(back_populates="private_content")
