"""share one free preview entitlement across analyses and readings

Revision ID: 20260806_19
Revises: 20260805_18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260806_19"
down_revision: str | None = "20260805_18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SHARED_CHECK = (
    "(free_preview_status = 'available' AND free_preview_analysis_id IS NULL "
    "AND free_preview_reading_id IS NULL AND free_preview_used_at IS NULL) OR "
    "(free_preview_status = 'reserved' AND "
    "((free_preview_analysis_id IS NOT NULL AND free_preview_reading_id IS NULL) OR "
    "(free_preview_analysis_id IS NULL AND free_preview_reading_id IS NOT NULL)) "
    "AND free_preview_used_at IS NULL) OR "
    "(free_preview_status = 'consumed' AND free_preview_used_at IS NOT NULL)"
)

_LEGACY_CHECK = (
    "(free_preview_status = 'available' AND free_preview_analysis_id IS NULL "
    "AND free_preview_used_at IS NULL) OR "
    "(free_preview_status = 'reserved' AND free_preview_analysis_id IS NOT NULL "
    "AND free_preview_used_at IS NULL) OR "
    "(free_preview_status = 'consumed' AND free_preview_used_at IS NOT NULL)"
)


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("free_preview_reading_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_users_preview_reading",
        "users",
        "readings",
        ["free_preview_reading_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.drop_constraint("ck_users_free_preview", "users", type_="check")
    op.create_check_constraint("ck_users_free_preview", "users", _SHARED_CHECK)


def downgrade() -> None:
    bind = op.get_bind()
    linked = bind.scalar(
        sa.text("SELECT count(*) FROM users WHERE free_preview_reading_id IS NOT NULL")
    )
    if linked:
        raise RuntimeError("downgrade refused: reading preview entitlement state exists")
    op.drop_constraint("ck_users_free_preview", "users", type_="check")
    op.drop_constraint("fk_users_preview_reading", "users", type_="foreignkey")
    op.drop_column("users", "free_preview_reading_id")
    op.create_check_constraint("ck_users_free_preview", "users", _LEGACY_CHECK)
