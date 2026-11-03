"""XIII's menu-level, question-mark-separated game description.

The GS field that contains this string has not yet been confirmed from a live
registration. The menu's construction and parsing are visible in disc scripts.
"""
from __future__ import annotations

from dataclasses import dataclass


def player_port(info: bytes) -> int:
    """Native u32 port supplied by XIII as its lobby player-info blob."""
    if len(info) != 4:
        raise ValueError("XIII player info requires one four-byte port")
    port = int.from_bytes(info, "little")
    if not 1 <= port <= 65535:
        raise ValueError("invalid XIII player-info port")
    return port


@dataclass(frozen=True)
class GameDescription:
    game_type_index: str
    map_index: str
    frag_limit: str
    time_limit: str
    private_flag: str

    @classmethod
    def parse(cls, value: str) -> "GameDescription":
        fields = value.split("?")
        if len(fields) != 5:
            raise ValueError("XIII game descriptions require five fields")
        return cls(*fields)

    def encode(self) -> str:
        fields = (self.game_type_index, self.map_index, self.frag_limit,
                  self.time_limit, self.private_flag)
        if any("?" in field for field in fields):
            raise ValueError("XIII game description fields cannot contain '?'")
        return "?".join(fields)

    @property
    def is_private(self) -> bool:
        return self.private_flag == "Y"


@dataclass(frozen=True)
class HostDescription:
    """Candidate XIII registration info recovered from both client paths.

    The containing GS binary field and its terminator have not been checked
    against a real game-registration packet.
    """
    description: GameDescription
    requested_max_players: int
    port: int

    @classmethod
    def parse(cls, value: str) -> "HostDescription":
        body, separator, port_text = value.partition(":")
        if not separator or ":" in port_text:
            raise ValueError("XIII host description requires one port separator")
        description, separator, maximum_text = body.rpartition("?")
        if not separator or not maximum_text.isascii() or not maximum_text.isdecimal():
            raise ValueError("invalid XIII player limit")
        if not port_text.isascii() or not port_text.isdecimal():
            raise ValueError("invalid XIII game port")
        maximum, port = int(maximum_text), int(port_text)
        if maximum < 1 or not 1 <= port <= 65535:
            raise ValueError("invalid XIII player limit or port")
        return cls(GameDescription.parse(description), maximum, port)

    def encode(self) -> str:
        if self.requested_max_players < 1 or not 1 <= self.port <= 65535:
            raise ValueError("invalid XIII player limit or port")
        description = self.description.encode()
        if ":" in description:
            raise ValueError("XIII host description fields cannot contain ':'")
        return f"{description}?{self.requested_max_players}:{self.port}"
