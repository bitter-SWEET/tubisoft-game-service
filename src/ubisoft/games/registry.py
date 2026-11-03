"""Explicit game catalog and listener bindings, independent of account identity."""
from dataclasses import dataclass
from types import MappingProxyType

from .base import GameProfile
from .gr2 import PROFILE as GR2
from .xiii import PROFILE as XIII

PROFILES = MappingProxyType({profile.slug: profile for profile in (XIII, GR2)})


@dataclass(frozen=True)
class GameBinding:
    profile: GameProfile
    router_port: int
    launcher_port: int
    nat_port: int


def bindings(environment) -> tuple[GameBinding, ...]:
    """Keep legacy XIII port variables; new titles use a slug-specific prefix."""
    slugs = [slug.strip() for slug in environment.get("TUBISOFT_GAMES", "xiii").split(",")]
    if not slugs or any(slug not in PROFILES for slug in slugs) or len(set(slugs)) != len(slugs):
        raise ValueError("TUBISOFT_GAMES must contain unique known game slugs")
    result = []
    used = set()
    http_port = int(environment.get("TUBISOFT_HTTP_PORT", 8080))
    for slug in slugs:
        profile = PROFILES[slug]
        prefix = "TUBISOFT_" if slug == "xiii" else f"TUBISOFT_{slug.upper()}_"
        ports = tuple(int(environment.get(prefix + name + "_PORT", default))
                      for name, default in zip(("ROUTER", "LAUNCHER", "NAT"), profile.default_ports))
        # Reject even cross-protocol overlap to keep configuration unambiguous.
        if any(not 1 <= port <= 65535 or port == http_port or port in used for port in ports) or len(set(ports)) != 3:
            raise ValueError("game ports must be valid, distinct, and separate from HTTP")
        used.update(ports)
        result.append(GameBinding(profile, *ports))
    return tuple(result)
