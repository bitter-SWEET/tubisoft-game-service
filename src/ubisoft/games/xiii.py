"""XIII's menu-level, question-mark-separated game description.

The GS field that contains this string has not yet been confirmed from a live
registration. The menu's construction and parsing are visible in disc scripts.
"""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress

from .base import GameProfile, RoomSpec


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


class XIIIProfile(GameProfile):
    def parent_lobby(self) -> list:
        return ["0", self.display_name, "1", "1", "0", "0", "1", "", "", "", b"", "0", "8", "0"]

    def launcher_groups(self) -> list:
        return [["1", "1", self.display_name, "0", "8"]]

    def registration(self, fields: list, peer_ip: str) -> RoomSpec:
        if (len(fields) != 3 or fields[0] != "12" or fields[1] != "1"
                or not isinstance(fields[2], list) or len(fields[2]) != 16):
            raise ValueError("unsupported registration structure")
        values = fields[2]
        types = (str, str, str, str, str, str, str, bytes, bytes,
                 str, str, str, str, str, str, bytes)
        if not all(isinstance(value, typ) for value, typ in zip(values, types)):
            raise ValueError("unsupported registration field types")
        if values[1] != "1" or values[3] != self.product:
            raise ValueError("unsupported registration parent or product")
        if values[9]:
            raise ValueError("password-protected room registration is not implemented")
        if any(not values[i].isascii() or not values[i].isdecimal() for i in (4, 5, 6, 12, 14)):
            raise ValueError("invalid registration numeric field")
        if not 1 <= int(values[14]) <= 65535:
            raise ValueError("invalid registration game port")
        if any(len(values[i]) > 16384 for i in (7, 8, 15)):
            raise ValueError("registration data exceeds local limit")
        try:
            local = ipaddress.IPv4Address(values[13])
            if local.is_unspecified or local.is_multicast or local.is_loopback or int(local) == 0xffffffff:
                raise ValueError("unusable supplied address")
            local_ip = str(local)
        except ValueError:
            local_ip = peer_ip
        return RoomSpec(values[2], values[3], values[4], values[1], values[12],
                        values[5], values[6], values[7], values[15], values[14],
                        values[10], values[11], local_ip)

    def group_flags(self, flags: str) -> str:
        # XIII's child-group callback requires bit 0x08 for discovery.
        return str(int(flags) | 0x08)

    def game_started_fields(self, room) -> list:
        # XIII's callback ignores the binary field. Keep both addresses usable:
        # it can choose the second one when public addresses match.
        return ["56", [str(room.room_id), b"", room.game_port, room.peer_ip, room.local_ip or room.peer_ip]]

    def player_port(self, info: bytes) -> int:
        return player_port(info)

    def member_events(self, room, username: str, ip: str, info: bytes, *, new: bool) -> list:
        # 0x01d66be0 reads indices 0,1,3,4,5,6; index 2 is unused.
        events = [["50", [username, "0", str(room.room_id), ip, "", b"", "0"]]] if new else []
        # 0x00383b00 consumes the native port and opens a NAT peer connection.
        events.append(["66", [username, info]])
        return events

    def member_left(self, username: str) -> list:
        return ["51", [username]]

    def host_operation(self, room, fields: list) -> list | None:
        if (not room.active or len(fields) != 2 or not isinstance(fields[0], str)
                or not isinstance(fields[1], list)):
            return None
        subtype, values = fields
        if not values or values[0] != str(room.room_id):
            return None
        if subtype == "17" and len(values) == 2 and isinstance(values[1], str):
            if not values[1].isascii() or not values[1].isdecimal():
                return None
        elif subtype == "45" and len(values) == 1:
            pass
        elif (subtype == "31" and len(values) == 3 and values[1] == "1024"
              and isinstance(values[2], bytes) and len(values[2]) <= 16384):
            room.additional_info = values[2]
        else:
            return None
        return [subtype, [str(room.room_id)]]


PROFILE = XIIIProfile(
    slug="xiii", product="XIIIPS2US", display_name="XIII", game_version="1.0",
    sdk_version="XIIIPS21.0", default_ports=(30000, 30001, 30002), supports_rooms=True,
)
