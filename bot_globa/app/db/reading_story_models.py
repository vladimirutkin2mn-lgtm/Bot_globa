"""Persistence for user-managed reading stories and encrypted titles."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, LargeBinary, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ReadingStory(Base):
    """Operational metadata for one user-owned story."""

    __tablename__ = "reading_stories"
    __table_args__ = (Index("ix_reading_stories_user_updated", "user_id", "updated_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    private_content: Mapped["ReadingStoryPrivateContent"] = relationship(
        back_populates="story",
        uselist=False,
        cascade="all, delete-orphan",
    )
    links: Mapped[list["ReadingStoryLink"]] = relationship(
        back_populates="story",
        cascade="all, delete-orphan",
        order_by="ReadingStoryLink.linked_at",
    )


class ReadingStoryPrivateContent(Base):
    """Purpose-separated ciphertext for a private story title."""

    __tablename__ = "reading_story_private_content"

    story_id: Mapped[UUID] = mapped_column(
        ForeignKey("reading_stories.id", ondelete="CASCADE"), primary_key=True
    )
    title_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    title_format_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    story: Mapped[ReadingStory] = relationship(back_populates="private_content")


class ReadingStoryLink(Base):
    """One manual story assignment for an existing ready reading."""

    __tablename__ = "reading_story_links"
    __table_args__ = (Index("ix_reading_story_links_story_linked", "story_id", "linked_at"),)

    reading_id: Mapped[UUID] = mapped_column(
        ForeignKey("readings.id", ondelete="CASCADE"), primary_key=True
    )
    story_id: Mapped[UUID] = mapped_column(
        ForeignKey("reading_stories.id", ondelete="CASCADE"), index=True
    )
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    story: Mapped[ReadingStory] = relationship(back_populates="links")
