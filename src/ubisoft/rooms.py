"""In-memory room state for the experimental local GS server.

The GS record layout here remains a candidate until verified with XIII. Raw
metadata is retained so that game-specific interpretation stays outside the
common registry.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable
import ipaddress
import time

PENDING_ROOM_SECONDS = 120
# XIII's discovery callback forwards a child group only when this bit is set.
# Its registration flags do not include the bit, so the lobby supplies it in
# the advertised record. The remaining flag meanings are still experimental.
DISCOVERABLE_GROUP_FLAG = 0x08


@dataclass
class Room:
    room_id: int
    owner: str
    peer_ip: str
    name: str
    product: str
    group_type: str
    parent_id: str
    flags: str
    max_players: str
    max_spectators: str
    info: bytes
    additional_info: bytes
    game_port: str
    game_version: str
    sdk_version: str
    local_ip: str = ""
    active: bool = False
    pending_until: float = 0
    members: set[tuple[str, str]] = field(default_factory=set)
    member_info: dict[tuple[str, str], bytes] = field(default_factory=dict)
    host_connections: set[object] = field(default_factory=set, repr=False)

    def game_started_fields(self) -> list:
        """Host endpoint consumed by XIII's game-started/join callback.

        The XIII parser reads room ID, opaque binary data, a decimal uint16
        port, and two address strings. Its game callback ignores the binary
        data. When the public address matches its own, XIII can select the
        second address; keep it nonempty to avoid its unchecked lookup path.
        """
        return ["56", [str(self.room_id), b"", self.game_port, self.peer_ip, self.local_ip or self.peer_ip]]

    def group_fields(self) -> list:
        """Candidate GS child-group record; client validation is pending."""
        advertised_flags = str(int(self.flags) | DISCOVERABLE_GROUP_FLAG)
        host = (self.peer_ip, self.owner)
        player_count = 1 + len(self.members - {host})
        return [self.group_type, self.name, str(self.room_id), "1", self.parent_id,
                advertised_flags, "2", self.owner, "", self.product, self.info, "0",
                self.max_players, str(player_count), self.max_spectators, "0",
                self.game_version, self.sdk_version, self.peer_ip, self.local_ip or self.peer_ip]


class RoomRegistry:
    def __init__(self) -> None:
        self._rooms: dict[int, Room] = {}
        self._next_id = 1000
        self._remove_listeners: set[Callable[[Room], None]] = set()

    def add_remove_listener(self, listener: Callable[[Room], None]) -> None:
        self._remove_listeners.add(listener)

    def remove_remove_listener(self, listener: Callable[[Room], None]) -> None:
        self._remove_listeners.discard(listener)

    def register(self, owner: str, peer_ip: str, fields: list) -> Room:
        self.expire_pending()
        if (len(fields) != 3 or fields[0] != "12" or fields[1] != "1"
                or not isinstance(fields[2], list) or len(fields[2]) != 16):
            raise ValueError("unsupported registration structure")
        values = fields[2]
        expected_types = (str, str, str, str, str, str, str, bytes, bytes,
                          str, str, str, str, str, str, bytes)
        if not all(isinstance(value, typ) for value, typ in zip(values, expected_types)):
            raise ValueError("unsupported registration field types")
        if values[1] != "1" or values[3] != "XIIIPS2US":
            raise ValueError("unsupported registration parent or product")
        if values[9]:
            raise ValueError("password-protected room registration is not implemented")
        if any(not values[i].isascii() or not values[i].isdecimal() for i in (4, 5, 6, 12, 14)):
            raise ValueError("invalid registration numeric field")
        if not 1 <= int(values[14]) <= 65535:
            raise ValueError("invalid registration game port")
        if any(len(values[i]) > 16384 for i in (7, 8, 15)):
            raise ValueError("registration data exceeds local limit")
        if any(room.owner == owner and room.peer_ip == peer_ip for room in self._rooms.values()):
            raise ValueError("owner already has a registered room")
        # The launcher supplies its connection address at index 13. Retain a
        # usable IPv4 value, otherwise use the observed address as a nonempty
        # fallback. Never put a missing/invalid hostname into the join reply.
        try:
            local = ipaddress.IPv4Address(values[13])
            if local.is_unspecified or local.is_multicast or local.is_loopback or int(local) == 0xffffffff:
                raise ValueError("unusable supplied address")
            local_ip = str(local)
        except ValueError:
            local_ip = peer_ip
        room = Room(self._next_id, owner, peer_ip, values[2], values[3], values[4],
                    values[1], values[12], values[5], values[6], values[7], values[15],
                    values[14], values[10], values[11],
                    local_ip=local_ip, pending_until=time.monotonic() + PENDING_ROOM_SECONDS)
        self._next_id += 1
        self._rooms[room.room_id] = room
        return room

    def activate(self, room_id: int, owner: str, peer_ip: str) -> Room | None:
        self.expire_pending()
        room = self._rooms.get(room_id)
        if room is None or room.owner != owner or room.peer_ip != peer_ip:
            return None
        room.active = True
        return room

    def expire_pending(self, now: float | None = None) -> None:
        """Discard registrations that never completed the host handoff."""
        if now is None:
            now = time.monotonic()
        for room_id, room in list(self._rooms.items()):
            if not room.active and room.pending_until <= now:
                del self._rooms[room_id]

    def bind_host(self, room: Room, owner: str, peer_ip: str, connection: object) -> bool:
        """Bind only the authenticated owner's actual room connection."""
        if self.active_room(room.room_id) is not room or (owner, peer_ip) != (room.owner, room.peer_ip):
            return False
        room.host_connections.add(connection)
        return True

    def unbind_host(self, room: Room, connection: object) -> bool:
        if connection not in room.host_connections:
            return False
        room.host_connections.remove(connection)
        if not room.host_connections and self.active_room(room.room_id) is room:
            self.remove(room.room_id, room.owner, room.peer_ip)
            return True
        return False

    def remove(self, room_id: int, owner: str, peer_ip: str) -> None:
        room = self._rooms.get(room_id)
        if room is not None and room.owner == owner and room.peer_ip == peer_ip:
            del self._rooms[room_id]
            room.active = False
            room.host_connections.clear()
            for listener in tuple(self._remove_listeners):
                listener(room)

    def active_room(self, room_id: int) -> Room | None:
        room = self._rooms.get(room_id)
        return room if room is not None and room.active else None

    def children(self) -> list:
        return [room.group_fields() for room in self._rooms.values() if room.active]
