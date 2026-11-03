"""GR2's verified bootstrap format; lobby/gameplay adapters remain research.

See docs/ghost-recon-2-network.md for executable evidence and remaining gaps.
Opting in enables shared GS authentication experiments, not working multiplayer.
"""
from .base import GameProfile

PROFILE = GameProfile(
    slug="gr2", product="GHOSTRECON2PS2", display_name="Ghost Recon 2",
    game_version="1.0", sdk_version="GR2PS21.0", default_ports=(30010, 30011, 30012),
    bootstrap_section="Servers",
    bootstrap_keys=("RouterIP0", "RouterPort0", "RouterLauncherPort0", "NATServerIP0", "NATServerPort0"),
)
