"""Add encrypted user-managed reading stories.

Revision ID: 20260911_39
Revises: 20260909_38
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260911_39"
down_revision: str | None = "20260909_38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reading_stories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reading_stories_user_id", "reading_stories", ["user_id"], unique=False)
    op.create_index(
        "ix_reading_stories_user_updated",
        "reading_stories",
        ["user_id", "updated_at"],
        unique=False,
    )

    op.create_table(
        "reading_story_private_content",
        sa.Column("story_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("title_format_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "title_format_version > 0",
            name="ck_reading_story_private_content_format",
        ),
        sa.ForeignKeyConstraint(
            ["story_id"],
            ["reading_stories.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("story_id"),
    )

    op.create_table(
        "reading_story_links",
        sa.Column("reading_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("story_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "linked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["reading_id"], ["readings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["story_id"], ["reading_stories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("reading_id"),
    )
    op.create_index(
        "ix_reading_story_links_story_id",
        "reading_story_links",
        ["story_id"],
        unique=False,
    )
    op.create_index(
        "ix_reading_story_links_story_linked",
        "reading_story_links",
        ["story_id", "linked_at"],
        unique=False,
    )


def downgrade() -> None:
    connection = op.get_bind()
    story_rows = connection.execute(sa.text("SELECT count(*) FROM reading_stories")).scalar_one()
    if story_rows:
        raise RuntimeError("downgrade refused: reading story data exists")

    op.drop_index("ix_reading_story_links_story_linked", table_name="reading_story_links")
    op.drop_index("ix_reading_story_links_story_id", table_name="reading_story_links")
    op.drop_table("reading_story_links")
    op.drop_table("reading_story_private_content")
    op.drop_index("ix_reading_stories_user_updated", table_name="reading_stories")
    op.drop_index("ix_reading_stories_user_id", table_name="reading_stories")
    op.drop_table("reading_stories")
