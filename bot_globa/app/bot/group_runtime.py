"""Compose the shipped group experience before the shared router is registered.

The group product evolved as additive, idempotent installers. Keeping the order in one
place makes the production dispatcher use the same latest mechanics that the focused
unit tests exercise, instead of silently serving only the original group router.
"""

from app.bot import group_compatibility_handlers as compatibility
from app.bot import group_p1_08 as p1
from app.bot import group_social_handlers as social
from app.bot import group_viral_handlers as viral
from app.bot import group_viral_upgrade as viral_upgrade


def install_group_runtime() -> None:
    """Install every group upgrade in dependency order; safe to call repeatedly."""

    social.install_group_social_mechanics()
    compatibility.install_group_compatibility_mechanics()
    viral.install_group_viral_mechanics()
    viral_upgrade.install_group_viral_upgrade()
    p1.install_group_p1_08()
