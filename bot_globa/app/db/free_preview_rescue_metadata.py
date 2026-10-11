"""Keep the one-time preview-rescue column visible to SQLAlchemy metadata.

Alembic owns the production migration, while tests and a few local tools create
isolated schemas from ``Base.metadata``. Registering the column here keeps those
schema construction paths aligned with the deployable migration without making
preview-rescue state part of the normal onboarding model API.
"""

from sqlalchemy import Column, DateTime

from app.db.models import User


def configure_free_preview_rescue_metadata() -> None:
    """Append the rescue marker once so metadata-created schemas match Alembic."""

    if "free_preview_rescue_used_at" in User.__table__.c:
        return
    User.__table__.append_column(
        Column("free_preview_rescue_used_at", DateTime(timezone=True), nullable=True)
    )
