"""Rainbow Six 3 (PS2) sign-in, discovery, ranking startup and parent lobby; rooms remain research.

Addresses refer to the expanded multiplayer image (``MP.SOZ`` inflated to
``0x00100000``; GP ``0x0065cf70``) of ``SLUS-20883``. See
docs/rainbow-six-3-network.md for the evidence and the remaining gaps.
Opting in enables shared GS authentication experiments, not working multiplayer.
"""
import ipaddress

from .base import GameProfile, RoomSpec

# Login state machine 0x00541c70 selects these codes. Its two branches use
# "ge" (0x005129a8) and "de" (0x00542dd4) respectively for German.
LANGUAGES = frozenset(("en", "ge", "de", "fr", "es", "it"))


def _decimal(value: str, maximum: int) -> int:
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal() or len(value) > 10:
        raise ValueError("invalid R6 numeric field")
    number = int(value)
    if number > maximum:
        raise ValueError("R6 numeric field out of range")
    return number


class R6Profile(GameProfile):
    def registration(self, fields: list, peer_ip: str) -> RoomSpec:
        # Lobby operation 12, sender 0x00417dd0: parent ID, room name,
        # product, three u16 values, game data, password, two version
        # strings and additional data. Caller 0x00404080 passes the new
        # room's group type (its entry +0x00, 5 in retail), the player limit
        # (entry +0xc8, shown as the list's maximum) and a constant 0
        # (spectators, entry +0xd0). The launcher 0xd5 path (0x00453ca0) is
        # not used by the retail Create Game menu.
        types = (str, str, str, str, str, str, bytes, str, str, str, bytes)
        if (len(fields) != len(types)
                or not all(isinstance(value, typ) for value, typ in zip(fields, types))):
            raise ValueError("unsupported R6 room creation structure")
        parent, name, product, group_type, players, spectators, info, password, version, sdk, extra = fields
        if parent != "1" or product != self.product:
            raise ValueError("unsupported R6 room parent or product")
        if password:
            raise ValueError("password-protected room creation is not implemented")
        if not name or len(name.encode()) > 32 or len(version.encode()) > 32 or len(sdk.encode()) > 32:
            raise ValueError("invalid R6 room text field")
        if not 1 <= _decimal(group_type, 0xffff):
            raise ValueError("invalid R6 room type")
        if not 1 <= _decimal(players, 0xffff) <= 64:
            raise ValueError("invalid R6 player limit")
        _decimal(spectators, 0xffff)
        if len(info) > 16384 or len(extra) > 16384:
            raise ValueError("R6 room data exceeds local limit")
        # The record's type is the creator's own (op-53 field 0 becomes the
        # entry's +0x00). The game port is learned from later room updates.
        return RoomSpec(name, product, group_type, parent, "0", players, spectators, info, extra,
                        "0", version, sdk, peer_ip)

    def lobby_create_result(self, room) -> list:
        # Reader 0x0041ba60: room ID (number), text (empty on success) and
        # the parent group ID, which 0x004284f0 uses to file the new child.
        return [str(room.room_id), "", room.parent_id]

    def room_join_result(self, room) -> list:
        # Reader 0x0041ab90 reads the room ID and a text field.
        return [str(room.room_id), ""]

    def group_flags(self, flags: str) -> str:
        return flags

    # Senders 0x00419440 (34), 0x00419270 (35), 0x004184b0 (44), 0x00418320
    # (45) and 0x00418640 (70) each send only the room ID and none has a
    # completion reader. The host sends 34 about three seconds after
    # creating a room, while its match loads.
    room_notice_subtypes = (34, 35, 44, 45, 70)

    def room_notice(self, room, subtype: int, values: list) -> None:
        if values != [str(room.room_id)]:
            raise ValueError("R6 room report does not name the joined room")

    def room_update(self, room, subtype: int, values: list) -> list:
        # Owner-only room operations issued through 0x0042a1d0. Their readers
        # (15: 0x0041f1e0, 17: 0x0041c0a0, 30: 0x0041e8c0, 31: 0x0041e420,
        # 33: 0x0041f680) each check the envelope and read only the room ID.
        if not isinstance(values, list) or not values or values[0] != str(room.room_id):
            raise ValueError("R6 room update does not name the owner's room")
        if subtype == 33:
            # Sender 0x00418f70: room ID, binary, number, address string.
            if (len(values) != 4 or not isinstance(values[1], bytes) or len(values[1]) > 16384
                    or not isinstance(values[3], str)):
                raise ValueError("unsupported R6 room address update")
            port = _decimal(values[2], 0xffff)
            if port:
                room.game_port = str(port)
            try:
                local = ipaddress.IPv4Address(values[3])
                # PCSX2's Sockets backend gives every emulated PS2 192.0.2.100
                # (documentation range); it is never a reachable LAN address.
                if not (local.is_unspecified or local.is_multicast or local.is_loopback
                        or local in ipaddress.IPv4Network("192.0.2.0/24")):
                    room.local_ip = str(local)
            except ValueError:
                pass
        elif subtype == 31:
            # Sender 0x004189d0 replaces the advertised game data.
            for value in values[1:]:
                if isinstance(value, bytes) and len(value) > 16384:
                    raise ValueError("R6 room data exceeds local limit")
            blobs = [value for value in values[1:] if isinstance(value, bytes)]
            if blobs:
                room.info = blobs[0]
        elif subtype == 17:
            if len(values) != 2:
                raise ValueError("unsupported R6 room state update")
            _decimal(values[1], 0xffffffff)
        elif len(values) != 1:
            raise ValueError("unsupported R6 room update")
        return [str(room.room_id)]

    def lobby_member_event(self, member) -> list:
        # Reader 0x004237f0 (operation 50) -> callback 0x004034a0: name, a
        # flag character, one group ID, two address strings, binary player
        # data and a u16. The callback files the member with that group and
        # the connection's lobby server ID. Match-list filler 0x004e1ea0
        # hides a player-hosted game (game data +0x48 nonzero) unless
        # 0x00401720 finds its owner among the members with the room's ID.
        # With 24 bytes of data (IPv4 + port, from 0x004013a0) a room owner
        # sends "PERMIT PING" (0x0050e2a0) to the member's game socket.
        return ["50", [member.name, "0", member.group, member.address,
                       member.local_address or member.address, member.info, "0"]]

    def lobby_member_left(self, member) -> list:
        # Reader 0x00423ea0 (operation 51): name (32 bytes max) and group ID.
        return ["51", [member.name, member.group]]

    def login_notices(self, fields: list) -> list:
        # 0x00410aa0 sends 0xde with one language string. Reader 0x00411f80
        # requires a nested list at field 1 holding two strings, each bounded
        # to a 0x201-byte buffer. No service notices are configured.
        if (len(fields) != 1 or not isinstance(fields[0], str)
                or fields[0] not in LANGUAGES):
            raise ValueError("unsupported R6 notice language")
        return ["", ""]

    def discovery_login(self, fields: list) -> None:
        # 0x00417500 sends 0xd1 ["21", [product]].
        self.require_discovery()
        if fields != [self.product]:
            raise ValueError("unsupported R6 discovery product")

    def parent_lobby(self) -> list:
        # Folder reader 0x00416f00 consumes 14 fields: u32 ID, name (33),
        # four numbers, u32, strings of 16/132/99 bytes, binary data, then
        # three numbers. The 20-field child-game reader is 0x00416c20.
        return ["0", self.display_name, "1", "1", "0", "0", "1", "", "",
                self.product, b"", "0", "8", "0"]

    def join_parent_lobby(self, fields: list) -> list:
        # Sender 0x004177e0 issues operation 23 through 0x0042a1d0 with group
        # ID, password and a numeric option. Completion reader 0x0041a730
        # checks the operation-23 envelope, then reads the group ID and an
        # optional string (default empty) from the nested list.
        from ..proxy import unsigned
        if (len(fields) != 3 or not all(isinstance(value, str) for value in fields)
                or fields[0] != "1" or fields[1] != ""):
            raise ValueError("unsupported R6 parent lobby join")
        unsigned(fields[2])
        return ["1", ""]

    def parent_player_info(self, fields: list) -> bytes:
        # Game function 0x004013a0 publishes 0x18 bytes from its GS player
        # record (via 0x0040b4a0 -> 0x00419980, operation 42) after joining
        # the parent and marks completion at offset 0x184. Reader 0x00421710
        # only checks the operation-42 success envelope.
        if len(fields) != 1 or not isinstance(fields[0], bytes) or len(fields[0]) != 24:
            raise ValueError("invalid R6 parent player data")
        return fields[0]

    def ranking_table(self, fields: list, username: str) -> list:
        # Serializer 0x004379d0 builds operation 1 with a six-field query:
        # application ID, product (copied by 0x00427d30), two unsigned
        # ladder/table values, [selection type 0-3, values] and three
        # column/sort/filter lists. Selection setters: type 1 [alias, count]
        # (0x00427910), type 2 [aliases] (0x00427a00), type 3 [start, count]
        # (0x00427b20). The transport envelope is the shared SDK form.
        from ..proxy import unsigned
        if (len(fields) != 2 or fields[0] != "1" or not isinstance(fields[1], list)
                or len(fields[1]) != 6):
            raise ValueError("unsupported R6 ranking request")
        query = fields[1]
        unsigned(query[0])
        unsigned(query[2])
        unsigned(query[3])
        if (query[1] != self.product
                or not isinstance(query[4], list) or len(query[4]) != 2
                or unsigned(query[4][0]) > 3 or not isinstance(query[4][1], list)
                or not isinstance(query[5], list) or len(query[5]) != 3
                or not all(isinstance(part, list) for part in query[5])):
            raise ValueError("unsupported R6 ranking selection")
        selection, values = query[4]
        columns = query[5][0]
        if selection == "2" and columns:
            # Sign-in callback 0x00485940 accepts an empty table as native
            # status -10 only for the type-1 "around player" and type-3 top
            # list queries. The three type-2 self queries (0x00485f50, columns
            # ALIAS and LEVEL) must parse a row in 0x00485250, otherwise the
            # LADDER stage of 0x00541c70 fails ("service not available").
            if (not values or len(values) > 16
                    or not all(isinstance(v, str) and 0 < len(v.encode()) < 0x81 for v in values)
                    or not all(isinstance(c, str) and 0 < len(c.encode()) < 0x21 for c in columns)
                    or len(set(columns)) != len(columns) or len(columns) > 32):
                raise ValueError("unsupported R6 ranking player selection")
            # Deserializer 0x0043d330: version "1", then [query ID, total,
            # columns as [field, name] pairs, rows of strings]. Field lookup
            # (0x0043d190) uses the first string; both carry the name. No
            # results are stored, so every non-alias field is an unranked 0.
            rows = [[alias if column == "ALIAS" else "0" for column in columns]
                    for alias in values]
            return ["1", [query[0], str(len(rows)), [[c, c] for c in columns], rows]]
        # No ranking records exist. The empty table keeps the application's
        # own query ID; 0x00485940 maps it to the native unranked status.
        return ["1", [query[0], "0", [], []]]


PROFILE = R6Profile(
    slug="r6", product="RAINBOWSIX3PS2US", display_name="Rainbow Six 3",
    # Setup 0x003ff3d0: product, SDK version "RSPS21.0", game version "1.0".
    game_version="1.0", sdk_version="RSPS21.0", default_ports=(30020, 30021, 30022),
    supports_discovery=True, supports_rooms=True, lobby_create=True, owner_game_started=False,
    lobby_members=True,
    # Game rooms have non-positive IDs: member callbacks 0x004034a0/0x00403220
    # count players (entry +0xcc, shown as the list's current players) and
    # set the in-room state only for IDs <= 0, and the group-change callback
    # 0x00401dd0 files IDs <= 0 as games. The GAME_STARTED callback
    # (0x00402520, via reader 0x004168e0) is empty, so it is not sent.
    negative_room_ids=True, game_started=False,
    proxy_services=("ladderquery",),
    # Reader 0x003ff9c0 looks up keys in [Servers] (GP-0x7880) and reads
    # RouterLauncherPortN separately, defaulting to 40005.
    bootstrap_section="Servers",
    bootstrap_keys=("RouterIP0", "RouterPort0", "RouterLauncherPort0", "NATServerIP0", "NATServerPort0"),
)
