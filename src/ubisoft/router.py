"""Experimental GS router: public-key handshake and bounded metadata logs.

This service provides experimental local account, lobby and room-registration
handlers. Their wire compatibility beyond observed flows remains unverified.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import secrets
import time
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from . import accounts, crypto, data, gsxor, nat, proxy, rooms, srp_probe
from .bootstrap import port_number
from .frame import GSHeader, HEADER_SIZE, read_frame
from .games.base import GameProfile
from .games.xiii import PROFILE as XIII
from .access import AccessPolicy

LOG = logging.getLogger("ubisoft.router")
KEY_EXCHANGE = 0xDB
PARENT_LOBBY = XIII.parent_lobby()  # Compatibility for existing protocol fixtures.


def response_header(request: GSHeader, payload: bytes, message_type: int | None = None) -> bytes:
    return GSHeader(HEADER_SIZE + len(payload), 0, request.priority,
                    request.message_type if message_type is None else message_type,
                    request.receiver, request.sender).encode()


def make_frame(request: GSHeader, fields: list) -> bytes:
    payload = gsxor.encrypt(data.encode(fields))
    return response_header(request, payload) + payload


def load_key(path: Path) -> rsa.RSAPrivateKey:
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, rsa.RSAPrivateKey) or key.key_size != 512:
        raise ValueError("router requires a 512-bit RSA private key")
    return key


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                 private_key: rsa.RSAPrivateKey, timeout: float, account_db: Path,
                 wait_host: str, wait_port: int,
                 pending_handoffs: dict[tuple[str, str], float],
                 authenticated: dict[tuple[str, str], float],
                 registry: rooms.RoomRegistry,
                 host_probe: srp_probe.Probe | None = None,
                 access_policy: AccessPolicy | None = None,
                 game_profile: GameProfile = XIII,
                 proxy_handoffs: proxy.Handoffs | None = None) -> None:
    peer = writer.get_extra_info("peername")
    local = writer.get_extra_info("sockname")
    LOG.info("connected game=%s peer=%s local=%s", game_profile.slug, peer, local)
    game_public: crypto.GSPublicKey | None = None
    client_key: bytes | None = None
    server_key: bytes | None = None
    logged_in_user: str | None = None
    wait_user: str | None = None
    lobby_logged_in = False
    joined_parent = False
    parent_info: bytes | None = None
    friends_logged_in = False
    proxy_user: str | None = None
    proxy_ready = False
    proxy_directory = proxy.Directory(game_profile, wait_host, wait_port)
    proxy_handoffs = proxy_handoffs if proxy_handoffs is not None else proxy.Handoffs()
    host_room: rooms.Room | None = None
    host_connection = object()
    joined_room: rooms.Room | None = None
    join_endpoint_sent = False
    host_member_notified = False
    closed_room_id: int | None = None

    def room_removed(room: rooms.Room) -> None:
        nonlocal joined_room, join_endpoint_sent, host_member_notified, closed_room_id
        if joined_room is not room:
            return
        # 0x01d73780 reads the nested room ID and removes the cached group.
        # Ending a hosted game does not invalidate the guest's GS sign-in.
        joined_room.members.discard((peer[0], wait_user.casefold()))
        joined_room.member_info.pop((peer[0], wait_user.casefold()), None)
        joined_room = None
        closed_room_id = room.room_id
        join_endpoint_sent = False
        host_member_notified = False
        payload = gsxor.encrypt(data.encode(["55", [str(room.room_id)]]))
        try:
            writer.write(GSHeader(HEADER_SIZE + len(payload), 0, 1, 0xd1, 2, 4).encode() + payload)
            LOG.info("room-closed notification sent peer=%s room=%d; sign-in session retained", peer, room.room_id)
        except (ConnectionError, OSError):
            LOG.info("room-closed notification skipped peer=%s: connection already closed", peer)

    registry.add_remove_listener(room_removed)
    async def account_operation(operation, *arguments):
        if access_policy is None:
            return await asyncio.to_thread(operation, *arguments)
        async with access_policy.hash_slots:
            return await asyncio.to_thread(operation, *arguments)
    try:
        while True:
            header, payload = await asyncio.wait_for(read_frame(reader, maximum_size=65535), timeout)
            LOG.info("frame peer=%s type=0x%02x property=%d size=%d sender=%d receiver=%d",
                     peer, header.message_type, header.property, header.size,
                     header.sender, header.receiver)
            if header.message_type == KEY_EXCHANGE and header.property == 0:
                fields = data.decode(gsxor.decrypt(payload))
                if (len(fields) != 2 or fields[0] not in ("1", "2")
                        or not isinstance(fields[1], list) or len(fields[1]) != 3
                        or not isinstance(fields[1][2], bytes)):
                    raise ValueError("unrecognized key exchange structure")
                subtype = fields[0]
                key_blob = fields[1][2]
                if subtype == "1":
                    game_public = crypto.GSPublicKey.decode(key_blob)
                    public = private_key.public_key().public_numbers()
                    public_bytes = crypto.GSPublicKey(private_key.key_size, public.n, public.e).encode()
                    writer.write(make_frame(header, ["1", ["1", str(len(public_bytes)), public_bytes]]))
                    LOG.info("key exchange peer=%s received=public bits=%d sent=public", peer, game_public.bits)
                else:
                    if game_public is None:
                        raise ValueError("cipher key received before public key")
                    client_key = private_key.decrypt(key_blob, padding.PKCS1v15())
                    if len(client_key) != 16:
                        raise ValueError("unexpected client cipher key length")
                    server_key = secrets.token_bytes(16)
                    encrypted = game_public.encrypt(server_key)
                    writer.write(make_frame(header, ["2", ["1", str(len(encrypted)), encrypted]]))
                    LOG.info("key exchange peer=%s received=cipher-key sent=cipher-key", peer)
                await writer.drain()
                continue
            if header.property == 2 and client_key is not None and server_key is not None:
                # XIII sends the first encrypted frame immediately after its key,
                # so check both possible directions without logging its contents.
                for direction, key in (("client", client_key), ("server", server_key)):
                    try:
                        decoded = crypto.decrypt_payload(key, payload)
                        fields = data.decode(decoded)
                    except ValueError:
                        continue
                    LOG.info("encrypted message peer=%s type=0x%02x key=%s decoded_fields=%d field_types=%s",
                             peer, header.message_type, direction, len(fields),
                             [type(field).__name__ for field in fields])
                    break
                else:
                    LOG.info("encrypted payload rejected peer=%s with both key directions", peer)
                    break
                if header.message_type == 1 and len(fields) == 7 and all(isinstance(field, str) for field in fields):
                    if access_policy is not None and not access_policy.allow_authentication(peer[0]):
                        LOG.info("account request throttled peer=%s", peer)
                        break
                    # Executable call chain: product version, username, password,
                    # followed by four optional fields.
                    created = await account_operation(accounts.create_account, account_db, fields[1], fields[2])
                    if created:
                        payload = gsxor.encrypt(data.encode([bytes([header.message_type])]))
                        writer.write(response_header(header, payload, 0x26) + payload)
                        await writer.drain()
                        LOG.info("account stored peer=%s; experimental success response sent", peer)
                    else:
                        LOG.info("account already exists peer=%s; duplicate response not implemented", peer)
                elif (header.message_type == 0x66 and len(fields) == 4
                      and all(isinstance(field, str) for field in fields[:3])
                      and isinstance(fields[3], bytes)):
                    if access_policy is not None and not access_policy.allow_authentication(peer[0]):
                        LOG.info("login request throttled peer=%s", peer)
                        break
                    if await account_operation(accounts.verify_account, account_db, fields[0], fields[1]):
                        payload = gsxor.encrypt(data.encode([bytes([header.message_type])]))
                        writer.write(response_header(header, payload, 0x26) + payload)
                        await writer.drain()
                        LOG.info("local login accepted peer=%s", peer)
                        logged_in_user = fields[0].casefold()
                        authenticated[(peer[0], logged_in_user)] = time.monotonic() + 120
                        continue
                    LOG.info("local login rejected peer=%s; failure response not implemented", peer)
                elif (header.message_type == 0x66 and len(fields) == 3
                      and all(isinstance(field, str) for field in fields)
                      and local[1] != wait_port):
                    if access_policy is not None and not access_policy.allow_authentication(peer[0]):
                        LOG.info("launcher login throttled peer=%s", peer)
                        break
                    # 0x00380b34 -> 0x00383f20 -> 0x01d64990 sends the
                    # same username/password as sign-in, then the version.
                    # Verify this connection's identity rather than guessing
                    # from the other accounts sharing its public IP.
                    if await account_operation(accounts.verify_account, account_db, fields[0], fields[1]):
                        logged_in_user = fields[0].casefold()
                        # Launcher callback 0x01d65440 requires a nested list
                        # containing a string in addition to the message ID.
                        payload = gsxor.encrypt(data.encode([b"\x66", [""]]))
                        writer.write(response_header(header, payload, 0x26) + payload)
                        await writer.drain()
                        LOG.info("launcher credentials accepted peer=%s", peer)
                        continue
                    LOG.info("launcher credentials rejected peer=%s", peer)
            else:
                proxy_route = (header.sender, header.receiver) == (8, 11) and bool(game_profile.proxy_services)
                if (proxy_route and header.property == 0 and header.message_type == 0x5d
                        and not payload and proxy_user is not None and not proxy_ready):
                    ticket = proxy_handoffs.issue(peer[0], proxy_user)
                    payload = gsxor.encrypt(data.encode([b"\x5d", [ticket, wait_host, str(wait_port)]]))
                    writer.write(response_header(header, payload, 0x26) + payload)
                    await writer.drain()
                    LOG.info("proxy redirect sent game=%s peer=%s", game_profile.slug, peer)
                    continue
                if (proxy_route and header.property == 0 and header.message_type == 0x3a
                        and not payload and proxy_ready):
                    writer.write(response_header(header, b""))
                    await writer.drain()
                    LOG.info("proxy heartbeat game=%s peer=%s", game_profile.slug, peer)
                    continue
                if (header.property == 0 and header.message_type == 0x5c
                        and not payload and wait_user is not None):
                    # Friends-disconnect is separate from router logout.
                    # 0x01d6cbd0 sends an empty message without awaiting a result.
                    friends_logged_in = False
                    LOG.info("friends channel disconnected peer=%s; sign-in session retained", peer)
                    continue
                if (header.property == 0 and header.message_type == 0x54
                        and not payload and wait_user is not None and friends_logged_in):
                    # GR2 0x004cece0 requests the ignore list with an empty
                    # body. Its completion reader (0x004cf740/0x004cc1a0)
                    # accepts GSSUCCESS containing only the binary operation
                    # ID. With no stored ignore entries, no item events follow.
                    payload = gsxor.encrypt(data.encode([b"\x54"]))
                    writer.write(response_header(header, payload, 0x26) + payload)
                    await writer.drain()
                    LOG.info("empty ignore list completed game=%s peer=%s", game_profile.slug, peer)
                    continue
                if (header.property == 0 and header.message_type == 0x3a
                        and not payload and wait_user is not None):
                    authenticated[(peer[0], wait_user.casefold())] = time.monotonic() + 120
                    # The retail TCP reader (0x01d4a7e0) times out after 180
                    # seconds without received bytes. Its outgoing STILLALIVE
                    # only updates the separate send clock. Return the empty
                    # frame on this connection, including the module route.
                    writer.write(response_header(header, b""))
                    await writer.drain()
                    LOG.info("wait module heartbeat peer=%s; empty STILLALIVE returned", peer)
                    continue
                if header.property == 0 and header.message_type == 0x5d and logged_in_user:
                    now = time.monotonic()
                    for key, expiry in list(pending_handoffs.items()):
                        if expiry <= now:
                            del pending_handoffs[key]
                    pending_handoffs[(peer[0], logged_in_user)] = now + 120
                    payload = gsxor.encrypt(data.encode([b"\x5d", [wait_host, wait_port.to_bytes(4, "little")]]))
                    writer.write(response_header(header, payload, 0x26) + payload)
                    await writer.drain()
                    LOG.info("wait module address sent peer=%s", peer)
                    continue
                if header.property == 0 and payload:
                    try:
                        fields = data.decode(gsxor.decrypt(payload))
                        LOG.info("plain message structure peer=%s count=%d field_types=%s", peer,
                                 len(fields), [type(field).__name__ for field in fields])
                        if (proxy_route and header.message_type == 0x66
                                and proxy_user is None and wait_user is None
                                and len(fields) == 2 and all(isinstance(field, str) for field in fields)):
                            if access_policy is not None and not access_policy.allow_authentication(peer[0]):
                                LOG.info("proxy login throttled game=%s peer=%s", game_profile.slug, peer)
                                break
                            # 0x004c8740 stores username at SDK+4, password at
                            # +0x14, and version at +0x25. Proxy setup passes
                            # +4/+0x25, so these are USERNAME/VERSION. Redeem
                            # the exact account's prior verified selection.
                            if not proxy_handoffs.consume_login(peer[0], fields[0], fields[1]):
                                LOG.info("proxy login grant rejected game=%s peer=%s", game_profile.slug, peer)
                                break
                            proxy_user = fields[0].casefold()
                            payload = gsxor.encrypt(data.encode([b"\x66", []]))
                            writer.write(response_header(header, payload, 0x26) + payload)
                            await writer.drain()
                            LOG.info("proxy login grant accepted game=%s peer=%s", game_profile.slug, peer)
                            continue
                        if (proxy_route and header.message_type == 0x4d
                                and proxy_user is None and wait_user is None
                                and len(fields) == 1 and isinstance(fields[0], str)):
                            proxy_user = proxy_handoffs.redeem(peer[0], fields[0])
                            if proxy_user is None:
                                LOG.info("proxy ticket rejected game=%s peer=%s", game_profile.slug, peer)
                                break
                            proxy_ready = True
                            payload = gsxor.encrypt(data.encode([b"\x4d", []]))
                            writer.write(response_header(header, payload, 0x26) + payload)
                            await writer.drain()
                            LOG.info("proxy ticket accepted game=%s peer=%s", game_profile.slug, peer)
                            continue
                        if header.message_type == 0xcc and wait_user is not None and not proxy_route:
                            reply = proxy_directory.reply(fields)
                            if fields[0] == "2":
                                proxy_handoffs.authorize_login(peer[0], wait_user, game_profile.sdk_version)
                            if reply is not None:
                                writer.write(make_frame(header, reply))
                                await writer.drain()
                            LOG.info("proxy directory handled game=%s peer=%s operation=%s",
                                     game_profile.slug, peer,
                                     fields[0][0] if isinstance(fields[0], list) else fields[0])
                            continue
                        if proxy_route and header.message_type == 0xcc and proxy_ready:
                            reply = proxy.query_reply(game_profile, fields, proxy_user)
                            writer.write(make_frame(header, reply))
                            await writer.drain()
                            LOG.info("empty ranking result game=%s peer=%s operation=%s request=%s",
                                     game_profile.slug, peer, fields[0], fields[1])
                            continue
                        if (header.message_type == 0xd9 and local[1] != wait_port
                                and logged_in_user is not None and len(fields) == 2
                                and all(isinstance(field, str) for field in fields)):
                            # Launcher callback 0x01d65750 expects a list of
                            # parent group records followed by an implicit end.
                            groups = game_profile.launcher_groups()
                            payload = gsxor.encrypt(data.encode([b"\xd9", groups]))
                            writer.write(response_header(header, payload, 0x26) + payload)
                            await writer.drain()
                            LOG.info("experimental launcher parent list sent peer=%s", peer)
                            continue
                        if (header.message_type == 0xd5 and local[1] != wait_port
                                and logged_in_user is not None):
                            if len(fields) == 3 and isinstance(fields[2], list):
                                LOG.info("registration structure peer=%s field_types=%s binary_lengths=%s",
                                         peer, [type(field).__name__ for field in fields[2]],
                                         [len(field) for field in fields[2] if isinstance(field, bytes)])
                            try:
                                created_room = registry.register(logged_in_user, peer[0], fields, game_profile)
                            except ValueError as exc:
                                LOG.info("registration rejected peer=%s reason=%s", peer, exc)
                                break
                            pending_handoffs[(peer[0], logged_in_user)] = created_room.pending_until
                            payload = gsxor.encrypt(data.encode([b"\xd5", [wait_host, str(wait_port),
                                                                              str(created_room.room_id), ""]]))
                            writer.write(response_header(header, payload, 0x26) + payload)
                            await writer.drain()
                            LOG.info("local room registered peer=%s id=%d; awaiting host login", peer, created_room.room_id)
                            continue
                        if (header.message_type == 0x4d and len(fields) == 1
                                and isinstance(fields[0], str)
                                and client_key is not None and server_key is not None):
                            key = (peer[0], fields[0].casefold())
                            expiry = pending_handoffs.pop(key, 0)
                            if expiry > time.monotonic():
                                payload = gsxor.encrypt(data.encode([b"\x4d"]))
                                writer.write(response_header(header, payload, 0x26) + payload)
                                await writer.drain()
                                wait_user = fields[0]
                                LOG.info("wait module login accepted peer=%s", peer)
                                continue
                            LOG.info("wait module login rejected peer=%s: no pending handoff", peer)
                        elif (header.message_type == 0xd2 and len(fields) >= 2
                              and isinstance(fields[0], str)
                              and isinstance(fields[1], (str, bytes))):
                            if len(fields) == 2:
                                game_profile.require_rooms()
                            else:
                                game_profile.require_discovery()
                            key = (peer[0], fields[0].casefold())
                            expiry = pending_handoffs.pop(key, 0)
                            if expiry > time.monotonic():
                                if len(fields) == 2:
                                    if not isinstance(fields[1], str) or not fields[1].isascii() or not fields[1].isdecimal():
                                        LOG.info("host lobby login rejected peer=%s: invalid room id", peer)
                                        break
                                    candidate_host_room = registry.activate(int(fields[1]), fields[0].casefold(), peer[0], game_profile.product)
                                    if candidate_host_room is None:
                                        LOG.info("host lobby login rejected peer=%s: room ownership mismatch", peer)
                                        break
                                    if host_room is not None and host_room is not candidate_host_room:
                                        registry.unbind_host(host_room, host_connection)
                                    host_room = candidate_host_room
                                    registry.bind_host(host_room, fields[0].casefold(), peer[0], host_connection)
                                payload = gsxor.encrypt(data.encode(["210", [fields[1]]]))
                                writer.write(response_header(header, payload, 0x26) + payload)
                                await writer.drain()
                                wait_user = fields[0]
                                LOG.info("lobby server login accepted peer=%s", peer)
                                lobby_logged_in = True
                                joined_parent = False
                                parent_info = None
                                continue
                            LOG.info("lobby server login rejected peer=%s: no pending handoff", peer)
                        elif header.message_type == 0xde and wait_user is not None:
                            notices = game_profile.login_notices(fields)
                            payload = gsxor.encrypt(data.encode([b"\xde", notices]))
                            writer.write(response_header(header, payload, 0x26) + payload)
                            await writer.drain()
                            LOG.info("login notices sent game=%s peer=%s", game_profile.slug, peer)
                            continue
                        elif (header.message_type == 0x13 and wait_user is not None
                              and len(fields) == 1 and isinstance(fields[0], str)
                              and fields[0].casefold() == wait_user.casefold()):
                            profile = [wait_user, wait_user, "", "", "", "", ""]
                            payload = gsxor.encrypt(data.encode([b"\x13", profile]))
                            writer.write(response_header(header, payload, 0x26) + payload)
                            await writer.drain()
                            LOG.info("player info sent peer=%s", peer)
                            continue
                        elif (header.message_type == 0x4e and wait_user is not None
                              and len(fields) == 2
                              and all(isinstance(field, bytes) and len(field) == 4 for field in fields)):
                            # The shared presence channel supports login and an
                            # empty ignore list; other operations remain explicit.
                            payload = gsxor.encrypt(data.encode([b"\x4e"]))
                            writer.write(response_header(header, payload, 0x26) + payload)
                            await writer.drain()
                            friends_logged_in = True
                            LOG.info("experimental friends login accepted peer=%s", peer)
                            continue
                        elif (header.message_type == 0xd1 and wait_user is not None
                              and len(fields) == 2 and isinstance(fields[0], str)
                              and isinstance(fields[1], list)
                              and fields[0].isascii() and fields[0].isdigit()
                              and len(fields[0]) <= 3):
                            subtype = int(fields[0])
                            LOG.info("lobby request game=%s peer=%s subtype=%d nested_types=%s",
                                     game_profile.slug, peer, subtype,
                                     [type(item).__name__ for item in fields[1]])
                            if subtype in (21, 3, 9, 8, 23) or (
                                    subtype == 42 and joined_parent and joined_room is None):
                                game_profile.require_discovery()
                            else:
                                game_profile.require_rooms()
                            if subtype == 21:
                                game_profile.discovery_login(fields[1])
                                payload = gsxor.encrypt(data.encode(["38", ["21"]]))
                                writer.write(response_header(header, payload, 0xd1) + payload)
                                # The title adapter supplies its tested parent record.
                                payload = gsxor.encrypt(data.encode(["53", ["1", "256", ["0"], [game_profile.parent_lobby()]]]))
                                writer.write(response_header(header, payload, 0xd1) + payload)
                                await writer.drain()
                                LOG.info("discovery login response and experimental parent lobby sent peer=%s", peer)
                                continue
                            if (subtype == 3 and len(fields[1]) >= 1
                                    and isinstance(fields[1][0], str) and fields[1][0] == "1"):
                                pending_handoffs[(peer[0], wait_user.casefold())] = time.monotonic() + 120
                                payload = gsxor.encrypt(data.encode(["38", ["3", ["1", wait_host, str(wait_port)]]]))
                                writer.write(response_header(header, payload, 0xd1) + payload)
                                await writer.drain()
                                LOG.info("lobby server address sent peer=%s", peer)
                                continue
                            if (subtype == 9 and len(fields[1]) >= 1
                                    and isinstance(fields[1][0], str) and fields[1][0] == "1"):
                                # Group-info notification with the actual local parent
                                # and no child game rooms; the prior subtype-9 reply
                                # caused XIII to report that the group did not exist.
                                payload = gsxor.encrypt(data.encode(["53", ["1", "256", game_profile.parent_lobby(), registry.children(game_profile.product)]]))
                                writer.write(response_header(header, payload, 0xd1) + payload)
                                await writer.drain()
                                LOG.info("lobby group sent peer=%s active_rooms=%d", peer, len(registry.children(game_profile.product)))
                                continue
                            if subtype == 23:
                                if not lobby_logged_in:
                                    raise ValueError("parent join requires lobby server login")
                                result = game_profile.join_parent_lobby(fields[1])
                                joined_parent = True
                                parent_info = None
                                payload = gsxor.encrypt(data.encode(["38", ["23", result]]))
                                writer.write(response_header(header, payload, 0xd1) + payload)
                                # The parent exists even when there are no
                                # hosted games. This is directory membership,
                                # not registration of a synthetic game room.
                                children = registry.children(game_profile.product)
                                payload = gsxor.encrypt(data.encode(["53", [
                                    "1", "256", game_profile.parent_lobby(), children]]))
                                writer.write(response_header(header, payload, 0xd1) + payload)
                                await writer.drain()
                                LOG.info("parent lobby join accepted game=%s peer=%s active_rooms=%d",
                                         game_profile.slug, peer, len(children))
                                continue
                            if subtype == 42 and joined_parent and joined_room is None:
                                parent_info = game_profile.parent_player_info(fields[1])
                                # 0x004db070 delegates to the common lobby
                                # success parser; no game endpoint belongs
                                # in this directory-level completion.
                                payload = gsxor.encrypt(data.encode(["38", ["42"]]))
                                writer.write(response_header(header, payload, 0xd1) + payload)
                                await writer.drain()
                                LOG.info("parent player data updated game=%s peer=%s bytes=%d",
                                         game_profile.slug, peer, len(parent_info))
                                continue
                            if (subtype == 24 and len(fields[1]) == 5
                                    and all(isinstance(item, str) for item in fields[1])):
                                values = fields[1]
                                if (not values[0].isascii() or not values[0].isdecimal()
                                        or len(values[0]) > 10 or values[1]
                                        or not all(value.isascii() and value.isdecimal() for value in values[2:4])):
                                    LOG.info("unsupported room join request peer=%s", peer)
                                    break
                                room = registry.active_room(int(values[0]), game_profile.product)
                                if room is None:
                                    LOG.info("room join rejected peer=%s: room unavailable", peer)
                                    break
                                member = (peer[0], wait_user.casefold())
                                if host_room is not None and host_room is not room:
                                    registry.unbind_host(host_room, host_connection)
                                    host_room = None
                                if joined_room is not None:
                                    joined_room.members.discard(member)
                                    joined_room.member_info.pop(member, None)
                                room.members.add(member)
                                joined_room = room
                                if registry.bind_host(room, wait_user.casefold(), peer[0], host_connection):
                                    host_room = room
                                join_endpoint_sent = False
                                host_member_notified = False
                                # XIII parser 0x01d72af0 expects the room ID in
                                # the inner list of this lobby-success envelope.
                                payload = gsxor.encrypt(data.encode(["38", ["24", game_profile.room_join_result(room)]]))
                                writer.write(response_header(header, payload, 0xd1) + payload)
                                # Populate the room record; this is separate
                                # from the GAME_STARTED join-completion event.
                                payload = gsxor.encrypt(data.encode(["53", [str(room.room_id), "64", room.group_fields()]]))
                                writer.write(response_header(header, payload, 0xd1) + payload)
                                await writer.drain()
                                LOG.info("experimental room join accepted peer=%s room=%d", peer, room.room_id)
                                continue
                            if (subtype == 46 and len(fields[1]) == 1
                                    and isinstance(fields[1][0], str)
                                    and fields[1][0].isascii() and fields[1][0].isdecimal()):
                                room = registry.active_room(int(fields[1][0]), game_profile.product)
                                if room is None:
                                    LOG.info("additional room info unavailable peer=%s", peer)
                                    continue
                                payload = gsxor.encrypt(data.encode(["38", ["46", [str(room.room_id), room.additional_info]]]))
                                writer.write(response_header(header, payload, 0xd1) + payload)
                                await writer.drain()
                                LOG.info("additional room info sent peer=%s room=%d", peer, room.room_id)
                                continue
                            if subtype == 34 and joined_room is not None:
                                if registry.active_room(joined_room.room_id, game_profile.product) is not joined_room:
                                    raise ValueError('game-connected worker unavailable')
                                game_profile.game_connected(joined_room, fields[1])
                                LOG.info('game connection reported game=%s peer=%s room=%d; GS session retained',
                                         game_profile.slug, peer, joined_room.room_id)
                                continue
                            if subtype == 70 and joined_room is not None:
                                game_profile.game_transition(joined_room, fields[1])
                                # This report does not leave the directory room
                                # or sign out. No native completion is consumed.
                                LOG.info('game transition reported game=%s peer=%s room=%d; GS session retained',
                                         game_profile.slug, peer, joined_room.room_id)
                                continue
                            if (subtype == 42 and joined_room is not None and len(fields[1]) == 1
                                    and isinstance(fields[1][0], bytes) and len(fields[1][0]) <= 16384):
                                if registry.active_room(joined_room.room_id) is not joined_room:
                                    LOG.info("player info rejected peer=%s: host room unavailable", peer)
                                    break
                                joined_room.member_info[(peer[0], wait_user.casefold())] = fields[1][0]
                                is_owner = (peer[0], wait_user.casefold()) == (joined_room.peer_ip, joined_room.owner)
                                if host_probe is not None and not is_owner and not joined_room.dedicated:
                                    guest_port = joined_room.profile.player_port(fields[1][0])
                                    notified = host_probe.member_info(joined_room, wait_user, peer[0],
                                                                      fields[1][0], new=not host_member_notified)
                                    host_member_notified |= notified
                                    LOG.info("member endpoint peer=%s game_port=%d host_notified=%s",
                                             peer, guest_port, notified)
                                payload = gsxor.encrypt(data.encode(["38", ["42"]]))
                                writer.write(response_header(header, payload, 0xd1) + payload)
                                # The room-join success only starts player-info
                                # setup. GAME_STARTED (56) reaches 0x01d8cdf0
                                # and the game's 0x00382670 completion callback.
                                if not join_endpoint_sent:
                                    payload = gsxor.encrypt(data.encode(joined_room.game_started_fields()))
                                    writer.write(response_header(header, payload, 0xd1) + payload)
                                    join_endpoint_sent = True
                                    LOG.info("host endpoint sent peer=%s room=%d host=%s port=%s",
                                             peer, joined_room.room_id, joined_room.peer_ip, joined_room.game_port)
                                await writer.drain()
                                LOG.info("player info updated peer=%s room=%d", peer, joined_room.room_id)
                                continue
                            if (subtype == 8 and len(fields[1]) == 1
                                    and isinstance(fields[1][0], str)):
                                group_id = fields[1][0]
                                # Cleanup can name the parent or reset sentinel,
                                # or repeat a leave after GROUP_REMOVE arrived.
                                allowed = {"0", "1"}
                                if joined_room is not None:
                                    allowed.add(str(joined_room.room_id))
                                if closed_room_id is not None:
                                    allowed.add(str(closed_room_id))
                                if group_id not in allowed:
                                    LOG.info("room leave ignored peer=%s: group not associated with this session", peer)
                                    continue
                                if group_id in ("0", "1"):
                                    joined_parent = False
                                    parent_info = None
                                if joined_room is not None:
                                    joined_room.members.discard((peer[0], wait_user.casefold()))
                                    joined_room.member_info.pop((peer[0], wait_user.casefold()), None)
                                    if host_probe is not None and host_member_notified:
                                        host_probe.notify_host(joined_room, [joined_room.profile.member_left(wait_user)])
                                host_member_notified = False
                                payload = gsxor.encrypt(data.encode(["38", ["8", [group_id]]]))
                                writer.write(response_header(header, payload, 0xd1) + payload)
                                await writer.drain()
                                LOG.info("room leave accepted peer=%s group=%s; sign-in session retained", peer, group_id)
                                joined_room = None
                                if host_room is not None:
                                    removed = registry.unbind_host(host_room, host_connection)
                                    LOG.info("owner left room peer=%s room=%d removed=%s", peer, host_room.room_id, removed)
                                    host_room = None
                                continue
                            LOG.info("unsupported lobby request peer=%s subtype=%d nested_types=%s", peer, subtype,
                                     [type(item).__name__ for item in fields[1]])
                    except ValueError as exc:
                        LOG.info("plain message rejected game=%s peer=%s reason=%s",
                                 game_profile.slug, peer, type(exc).__name__)
                LOG.info("unhandled message peer=%s type=0x%02x", peer, header.message_type)
            # Avoid fabricating account creation or login results.
            break
    except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError,
            ValueError, TypeError) as exc:
        LOG.info("closed peer=%s reason=%s", peer, type(exc).__name__)
    finally:
        registry.remove_remove_listener(room_removed)
        if joined_room is not None and wait_user is not None:
            joined_room.members.discard((peer[0], wait_user.casefold()))
            joined_room.member_info.pop((peer[0], wait_user.casefold()), None)
            if host_probe is not None and host_member_notified:
                host_probe.notify_host(joined_room, [joined_room.profile.member_left(wait_user)])
        if host_room is not None:
            removed = registry.unbind_host(host_room, host_connection)
            LOG.info("owner room connection closed peer=%s room=%d removed=%s", peer, host_room.room_id, removed)
        writer.close()
        try:
            await writer.wait_closed()
        except ConnectionError:
            pass


async def serve(args: argparse.Namespace) -> None:
    key = load_key(args.private_key)
    pending_handoffs: dict[tuple[str, str], float] = {}
    authenticated: dict[tuple[str, str], float] = {}
    registry = rooms.RoomRegistry()
    game_profile = getattr(args, "game_profile", XIII)
    worker_path = getattr(args, "worker_state", None)
    if worker_path is not None:
        from .gr2_worker import read_worker
        registry.worker_provider = lambda: read_worker(worker_path, game_profile)
    proxy_handoffs = proxy.Handoffs()
    host_probe = srp_probe.Probe(pending_handoffs, registry, game_profile)
    advertise_ip = getattr(args, "advertise_ip", None) or args.bind
    access_policy = getattr(args, "access_policy", None)
    async def callback(reader, writer):
        peer_ip = writer.get_extra_info("peername")[0]
        if access_policy is not None and not access_policy.acquire(peer_ip):
            writer.close()
            await writer.wait_closed()
            return
        try:
            await handle(reader, writer, key, args.timeout, args.account_db, advertise_ip, args.port,
                         pending_handoffs, authenticated, registry, host_probe, access_policy, game_profile,
                         proxy_handoffs)
        finally:
            if access_policy is not None:
                access_policy.release(peer_ip)
    server = await asyncio.start_server(callback, args.bind, args.port)
    launcher = None
    udp_transport = None
    nat_transport = None
    worker_task = None
    try:
        if worker_path is not None:
            async def watch_worker():
                while True:
                    registry.sync_worker()
                    await asyncio.sleep(1)
            worker_task = asyncio.create_task(watch_worker())
        udp_transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
            lambda: host_probe, local_addr=(args.bind, args.port))
        if args.nat_port:
            nat_transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
                lambda: nat.Discovery(args.nat_allowed_cidr), local_addr=(args.bind, args.nat_port))
        if args.launcher_port:
            launcher = await asyncio.start_server(callback, args.bind, args.launcher_port)
            LOG.info("experimental launcher listening at %s", launcher.sockets[0].getsockname())
        LOG.info("router handshake listening at %s", server.sockets[0].getsockname())
        await server.serve_forever()
    finally:
        if worker_task is not None:
            worker_task.cancel()
            await asyncio.gather(worker_task, return_exceptions=True)
        server.close()
        await server.wait_closed()
        if udp_transport is not None:
            udp_transport.close()
        if nat_transport is not None:
            nat_transport.close()
        if launcher is not None:
            launcher.close()
            await launcher.wait_closed()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--advertise-ip", help="address clients can reach; defaults to the bind address")
    parser.add_argument("--port", type=port_number, default=30000)
    parser.add_argument("--launcher-port", type=port_number)
    parser.add_argument("--nat-port", type=port_number)
    parser.add_argument("--nat-allowed-cidr", default="127.0.0.0/8")
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--account-db", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    if not 0 < args.timeout <= 300:
        parser.error("timeout must be between 0 and 300 seconds")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
