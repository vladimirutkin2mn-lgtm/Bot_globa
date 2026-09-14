"""Compose the shipped group experience before the shared router is registered.

The group product evolved as additive, idempotent installers. Keeping the order in one
place makes the production dispatcher use the same latest mechanics that the focused
unit tests exercise, instead of silently serving only the original group router.
"""

from app.bot.group_cjm_v3 import install_group_cjm_v3
from app.bot.group_compatibility_handlers import install_group_compatibility_mechanics
from app.bot.group_compatibility_ux import install_group_compatibility_ux
from app.bot.group_duel_cjm import install_group_duel_cjm
from app.bot.group_p1_08 import install_group_p1_08
from app.bot.group_private_cjm import install_group_private_cjm
from app.bot.group_social_handlers import install_group_social_mechanics
from app.bot.group_viral_handlers import install_group_viral_mechanics
from app.bot.group_viral_upgrade import install_group_viral_upgrade


def install_group_runtime() -> None:
    """Install every group upgrade in dependency order; safe to call repeatedly."""

    install_group_social_mechanics()
    install_group_compatibility_mechanics()
    install_group_compatibility_ux()
    install_group_viral_mechanics()
    install_group_viral_upgrade()
    install_group_p1_08()
    install_group_duel_cjm()
    install_group_cjm_v3()
    install_group_private_cjm()
