import asyncio
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ubisoft import data, gsxor, router, srp_probe
from ubisoft.frame import GSHeader, HEADER_SIZE
from ubisoft.rooms import RoomRegistry


def frame(message_type, fields, property=0):
    payload = gsxor.encrypt(data.encode(fields))
    return GSHeader(HEADER_SIZE + len(payload), property, 1, message_type, 1, 2).encode() + payload


class Writer:
    def __init__(self, peer, local_port):
        self.peer = peer
        self.local_port = local_port
        self.output = bytearray()

    def get_extra_info(self, name):
        return {"peername": (self.peer, 1234), "sockname": ("192.0.2.1", self.local_port)}.get(name)

    def write(self, value):
        self.output.extend(value)

    async def drain(self):
        pass

    def close(self):
        pass

    async def wait_closed(self):
        pass


class HandoffTests(unittest.IsolatedAsyncioTestCase):
    async def test_host_room_removal_notifies_guest_and_preserves_authenticated_lobby(self):
        registry = RoomRegistry()
        host_ip, guest_ip = "192.0.2.2", "192.0.2.3"
        room = registry.register("host", host_ip, ["12", "1", [
            "launcher", "1", "Example", "XIIIPS2US", "6", "16", "0", b"info", b"\0", "",
            "1.0", "XIIIPS21.0", "8208", host_ip, "7777", b""]])
        registry.activate(room.room_id, room.owner, room.peer_ip)
        reader = asyncio.StreamReader()
        reader.feed_data(frame(0xd2, ["guest", "1", "", "", ""]))
        reader.feed_data(frame(0xd1, ["24", [str(room.room_id), "", "0", "0", "XIIIPS2US"]]))
        reader.feed_data(frame(0xd1, ["42", [(64508).to_bytes(4, "little")]]))
        writer = Writer(guest_ip, 30000)
        authenticated = {(guest_ip, "guest"): time.monotonic() + 60}
        task = asyncio.create_task(router.handle(
            reader, writer, None, 1, Path("/unused"), "192.0.2.1", 30000,
            {(guest_ip, "guest"): time.monotonic() + 60}, authenticated, registry))
        async def wait_for_membership():
            while (guest_ip, "guest") not in room.member_info:
                await asyncio.sleep(0)
        try:
            await asyncio.wait_for(wait_for_membership(), 1)
            registry.remove(room.room_id, room.owner, room.peer_ip)
            # The same connection can refresh after its room disappears.
            reader.feed_data(frame(0xd1, ["8", ["0"]]))
            reader.feed_data(frame(0xd1, ["8", [str(room.room_id)]]))
            reader.feed_data(frame(0xd1, ["9", ["1"]]))
            reader.feed_eof()
            await task
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        replies = []
        offset = 0
        while offset < len(writer.output):
            header = GSHeader.decode(writer.output[offset:offset + HEADER_SIZE])
            replies.append(data.decode(gsxor.decrypt(bytes(writer.output[offset + HEADER_SIZE:offset + header.size]))))
            offset += header.size
        self.assertEqual(replies[-4], ["55", [str(room.room_id)]])
        self.assertEqual(replies[-3:-1], [["38", ["8", ["0"]]], ["38", ["8", [str(room.room_id)]]]])
        self.assertEqual(replies[-1], ["53", ["1", "256", router.PARENT_LOBBY, []]])
        self.assertGreater(authenticated[(guest_ip, "guest")], time.monotonic())
        self.assertEqual(room.members, set())

    async def test_host_self_join_accepts_empty_player_info_and_keeps_lobby_usable(self):
        registry = RoomRegistry()
        host_ip = "192.0.2.2"
        room = registry.register("host", host_ip, ["12", "1", [
            "launcher", "1", "Example", "XIIIPS2US", "6", "16", "0", b"info", b"\0", "",
            "1.0", "XIIIPS21.0", "8208", host_ip, "7777", b""]])
        registry.activate(room.room_id, "host", host_ip)
        reader = asyncio.StreamReader()
        reader.feed_data(frame(0xd2, ["host", "1", "", "", ""]))
        reader.feed_data(frame(0xd1, ["24", [str(room.room_id), "", "0", "0", "XIIIPS2US"]]))
        reader.feed_data(frame(0xd1, ["42", [b""]]))
        reader.feed_data(frame(0xd1, ["46", [str(room.room_id)]]))
        reader.feed_eof()
        writer = Writer(host_ip, 30000)
        probe = SimpleNamespace(member_info=lambda *args, **kwargs: self.fail("host must not open a peer to itself"))
        await router.handle(reader, writer, None, 1, Path("/unused"), "192.0.2.1", 30000,
                            {(host_ip, "host"): time.monotonic() + 60}, {}, registry, probe)
        replies = []
        offset = 0
        while offset < len(writer.output):
            header = GSHeader.decode(writer.output[offset:offset + HEADER_SIZE])
            replies.append(data.decode(gsxor.decrypt(bytes(writer.output[offset + HEADER_SIZE:offset + header.size]))))
            offset += header.size
        self.assertIn(["38", ["42"]], replies)
        self.assertIn(room.game_started_fields(), replies)
        self.assertEqual(replies[-1], ["38", ["46", [str(room.room_id), b""]]])
        self.assertIs(registry.active_room(room.room_id), room)

    async def test_launcher_disconnect_does_not_discard_pending_host_room(self):
        registry = RoomRegistry()
        peer = "192.0.2.2"
        pending = {}
        authenticated = {(peer, "host"): time.monotonic() + 60}
        registration = ["12", "1", ["launcher", "1", "Example", "XIIIPS2US", "6", "16", "0",
                                    b"info", b"\0", "", "1.0", "XIIIPS21.0", "8208",
                                    peer, "7777", b""]]
        reader = asyncio.StreamReader()
        reader.feed_data(frame(0xdb, ["1", ["1", "0", b"key"]]))
        reader.feed_data(frame(0xdb, ["2", ["1", "0", b"key"]]))
        reader.feed_data(frame(0x66, [], property=2))
        reader.feed_data(frame(0xd5, registration))
        reader.feed_eof()
        writer = Writer(peer, 30001)
        public = SimpleNamespace(bits=512, encrypt=lambda key: b"encrypted", encode=lambda: b"public")
        key = SimpleNamespace(key_size=512, decrypt=lambda blob, padding: b"x" * 16,
                              public_key=lambda: SimpleNamespace(public_numbers=lambda: SimpleNamespace(n=1, e=3)))
        with patch.object(router.crypto, "GSPublicKey") as public_class, \
             patch.object(router.crypto, "decrypt_payload", return_value=data.encode(["a", "b", "c"])):
            public_class.decode.return_value = public
            public_class.return_value = public
            await router.handle(reader, writer, key, 1, Path("/unused"), "192.0.2.1", 30000,
                                pending, authenticated, registry)
        self.assertIn((peer, "host"), pending)
        self.assertIsNotNone(registry.activate(1000, "host", peer))

    async def test_friend_login_keeps_wait_connection_usable(self):
        peer = "192.0.2.3"
        pending = {(peer, "guest"): time.monotonic() + 60}
        authenticated = {}
        reader = asyncio.StreamReader()
        reader.feed_data(frame(0xd2, ["guest", "1", "", "", ""]))
        reader.feed_data(frame(0x4e, [b"1234", b"5678"]))
        reader.feed_data(GSHeader(HEADER_SIZE, 0, 1, 0x5c, 1, 2).encode())
        reader.feed_data(GSHeader(HEADER_SIZE, 0, 1, 0x3a, 1, 2).encode())
        reader.feed_eof()
        writer = Writer(peer, 30000)
        await router.handle(reader, writer, None, 1, Path("/unused"), "192.0.2.1", 30000,
                            pending, authenticated, RoomRegistry())
        first = GSHeader.decode(writer.output[:HEADER_SIZE])
        second = GSHeader.decode(writer.output[first.size:first.size + HEADER_SIZE])
        self.assertEqual(second.message_type, 0x26)
        self.assertEqual(data.decode(gsxor.decrypt(bytes(writer.output[first.size + HEADER_SIZE:]))), [b"\x4e"])
        self.assertIn((peer, "guest"), authenticated)

    async def test_guest_refresh_sees_active_room_from_another_ip(self):
        registry = RoomRegistry()
        host_ip, guest_ip = "192.0.2.2", "192.0.2.3"
        registration = ["12", "1", ["launcher", "1", "Example", "XIIIPS2US", "6", "16", "0",
                                    b"description:7777", b"\0", "", "1.0", "XIIIPS21.0",
                                    "8208", host_ip, "7777", b""]]
        room = registry.register("host", host_ip, registration)
        registry.activate(room.room_id, "host", host_ip)
        pending = {(guest_ip, "guest"): time.monotonic() + 60}
        reader = asyncio.StreamReader()
        reader.feed_data(frame(0xd2, ["guest", "1", "", "", ""]))
        reader.feed_data(frame(0xd1, ["9", ["1"]]))
        reader.feed_eof()
        writer = Writer(guest_ip, 30000)
        await router.handle(reader, writer, None, 1, Path("/unused"), "192.0.2.1", 30000,
                            pending, {}, registry)
        first = GSHeader.decode(writer.output[:HEADER_SIZE])
        notification = GSHeader.decode(writer.output[first.size:first.size + HEADER_SIZE])
        self.assertEqual(notification.message_type, 0xd1)
        fields = data.decode(gsxor.decrypt(bytes(writer.output[first.size + HEADER_SIZE:])))
        self.assertEqual(fields[0], "53")
        self.assertEqual(fields[1][3][0][2], str(room.room_id))
        self.assertEqual(int(fields[1][3][0][5]), 0x2018)
        self.assertEqual(fields[1][3][0][18], host_ip)

    async def test_guest_join_and_leave_use_registered_room(self):
        registry = RoomRegistry()
        host_ip, guest_ip = "192.0.2.2", "192.0.2.3"
        registration = ["12", "1", ["launcher", "1", "Example", "XIIIPS2US", "6", "16", "0",
                                    b"description:7777", b"\0", "", "1.0", "XIIIPS21.0",
                                    "8208", host_ip, "7777", b""]]
        room = registry.register("host", host_ip, registration)
        registry.activate(room.room_id, "host", host_ip)
        pending = {(guest_ip, "guest"): time.monotonic() + 60}
        reader = asyncio.StreamReader()
        reader.feed_data(frame(0xd2, ["guest", "1", "", "", ""]))
        room.additional_info = b"host=0"
        reader.feed_data(frame(0xd1, ["46", [str(room.room_id)]]))
        reader.feed_data(frame(0xd1, ["24", [str(room.room_id), "", "0", "0", "XIIIPS2US"]]))
        player_info = (64510).to_bytes(4, "little")
        updated_info = (64511).to_bytes(4, "little")
        reader.feed_data(frame(0xd1, ["42", [player_info]]))
        reader.feed_data(frame(0xd1, ["42", [updated_info]]))
        reader.feed_data(frame(0xd1, ["8", [str(room.room_id)]]))
        reader.feed_eof()
        writer = Writer(guest_ip, 30000)
        host_packets = []
        host_probe = srp_probe.Probe({}, registry)
        host_probe.transport = SimpleNamespace(sendto=lambda packet, peer: host_packets.append((packet, peer)))
        host_peer = (host_ip, 1024)
        host_probe.sessions[host_peer] = srp_probe.Session(0x1234, 0, next_segment=19, room=room)
        await router.handle(reader, writer, None, 1, Path("/unused"), "192.0.2.1", 30000,
                            pending, {}, registry, host_probe)
        offset = 0
        replies = []
        while offset < len(writer.output):
            header = GSHeader.decode(writer.output[offset:offset + HEADER_SIZE])
            payload = bytes(writer.output[offset + HEADER_SIZE:offset + header.size])
            replies.append((header.message_type, data.decode(gsxor.decrypt(payload))))
            offset += header.size
        self.assertEqual(replies[1], (0xd1, ["38", ["46", [str(room.room_id), b"host=0"]]]))
        self.assertEqual(replies[2], (0xd1, ["38", ["24", [str(room.room_id)]]]))
        self.assertEqual(replies[3][1][:1], ["53"])
        self.assertEqual(replies[3][1][1][:2], [str(room.room_id), "64"])
        self.assertEqual(replies[3][1][1][2][13], "2")
        self.assertEqual(replies[4:], [(0xd1, ["38", ["42"]]),
                                        (0xd1, ["56", [str(room.room_id), b"", "7777", host_ip, ""]]),
                                        (0xd1, ["38", ["42"]]),
                                        (0xd1, ["38", ["8", [str(room.room_id)]]])])
        self.assertEqual(room.members, set())
        self.assertEqual(room.member_info, {})
        # The guest TCP update reaches only the owning host's UDP channel.
        self.assertEqual([peer for _, peer in host_packets], [host_peer] * 3)
        self.assertEqual([srp_probe.HEADER.unpack_from(packet)[4] for packet, _ in host_packets], [19, 0, 1])
        events = []
        for packet, _ in host_packets:
            offset = srp_probe.HEADER.size
            payload_end = offset + srp_probe.HEADER.unpack_from(packet)[2]
            self.assertEqual(len(packet) % 2, 0)
            while offset < payload_end:
                header = GSHeader.decode(packet[offset:offset + HEADER_SIZE])
                self.assertEqual((header.message_type, header.sender, header.receiver), (0xd1, 2, 4))
                events.append(data.decode(gsxor.decrypt(packet[offset + HEADER_SIZE:offset + header.size])))
                offset += header.size
        self.assertEqual(events, [["50", ["guest", "0", str(room.room_id), guest_ip, "", b"", "0"]],
                                  ["66", ["guest", player_info]], ["66", ["guest", updated_info]],
                                  ["51", ["guest"]]])
