"""Cross-title boundaries tested with synthetic profiles and real GS sockets."""
import asyncio
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import socket
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from cryptography.hazmat.primitives.asymmetric import padding

from ubisoft import accounts, crypto, data, gsxor, router, service
from ubisoft.bootstrap import handle
from ubisoft.frame import GSHeader, HEADER_SIZE, read_frame
from ubisoft.games.base import UnsupportedOperation
from ubisoft.games.registry import GR2, XIII
from ubisoft.rooms import RoomRegistry


def registration(product):
    return ["12", "1", ["launcher", "1", "Same name", product, "6", "16", "0",
                         b"opaque", b"\0", "", "1.0", "fixture-sdk", "8208",
                         "192.0.2.2", "7777", b""]]


class ProfileTests(unittest.TestCase):
    def test_xiii_wire_format_is_preserved_and_gr2_uses_its_native_ini_dialect(self):
        self.assertEqual(XIII.bootstrap("192.0.2.1", 30000, 30001, "192.0.2.1", 30002),
                         b"routerip0=192.0.2.1\r\nrouterport0=30000\r\nrouterlauncherport0=30001\r\n"
                         b"natserverip0=192.0.2.1\r\nnatserverport0=30002\r\n")
        body = GR2.bootstrap("192.0.2.1", 30010, 30011, "192.0.2.1", 30012)
        self.assertEqual(body, b"[Servers]\r\nRouterIP0=192.0.2.1\r\nRouterPort0=30010\r\n"
                         b"RouterLauncherPort0=30011\r\nNATServerIP0=192.0.2.1\r\nNATServerPort0=30012\r\n")
        self.assertLess(len(body), 1460)

    def test_room_catalog_and_activation_are_scoped_even_for_same_owner_and_ip(self):
        other = replace(XIII, slug="fixture", product="FIXTURE")
        registry = RoomRegistry()
        first = registry.register("shared", "192.0.2.2", registration(XIII.product), XIII)
        second = registry.register("shared", "192.0.2.2", registration(other.product), other)
        self.assertIsNone(registry.activate(second.room_id, "shared", second.peer_ip, XIII.product))
        for room in (first, second):
            self.assertIs(registry.activate(room.room_id, room.owner, room.peer_ip, room.product), room)
            self.assertEqual([record[2] for record in registry.children(room.product)], [str(room.room_id)])
        self.assertIsNone(registry.active_room(second.room_id, XIII.product))
        with self.assertRaises(ValueError):
            registry.register("other", first.peer_ip, registration(other.product), XIII)

    def test_gr2_does_not_inherit_xiii_room_schemas(self):
        registry = RoomRegistry()
        with self.assertRaises(UnsupportedOperation):
            registry.register("shared", "192.0.2.2", registration(GR2.product), GR2)
        for operation in (GR2.parent_lobby, GR2.launcher_groups):
            with self.assertRaises(UnsupportedOperation):
                operation()
        self.assertEqual(registry.children(GR2.product), [])

    def test_config_requires_explicit_known_titles_and_nonoverlapping_ports(self):
        env = {"TUBISOFT_ADVERTISE_IP": "192.0.2.1"}
        self.assertEqual([b.profile for b in service.configuration(env).games], [XIII])
        both = service.configuration(env | {"TUBISOFT_GAMES": "xiii,gr2"})
        self.assertEqual([b.profile for b in both.games], [XIII, GR2])
        for extra in ({"TUBISOFT_GAMES": ""}, {"TUBISOFT_GAMES": "xiii,xiii"},
                      {"TUBISOFT_GAMES": "unknown"}, {"TUBISOFT_ROUTER_PORT": "8080"},
                      {"TUBISOFT_GAMES": "xiii,gr2", "TUBISOFT_GR2_ROUTER_PORT": "30000"},
                      {"TUBISOFT_GAMES": "gr2", "TUBISOFT_GR2_NAT_PORT": "65536"}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                service.configuration(env | extra)


class BootstrapDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_unknown_and_duplicate_products_are_not_served_and_user_is_not_logged(self):
        products = {GR2.product: b"gr2-only"}
        server = await asyncio.start_server(lambda r, w: handle(r, w, products), "127.0.0.1", 0)
        self.addAsyncCleanup(server.wait_closed)
        self.addCleanup(server.close)
        port = server.sockets[0].getsockname()[1]
        with self.assertLogs("ubisoft.bootstrap", level="INFO") as logs:
            for query, expected in (("dp=GHOSTRECON2PS2&user=private-fixture", b"200 OK"),
                                    ("dp=XIIIPS2US", b"404 Not Found"),
                                    ("dp=GHOSTRECON2PS2&dp=XIIIPS2US", b"404 Not Found"),
                                    ("dp=UNKNOWN", b"404 Not Found")):
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                writer.write(f"GET /gsinit.php?{query} HTTP/1.0\r\n\r\n".encode())
                await writer.drain()
                response = await asyncio.wait_for(reader.read(), 2)
                writer.close()
                await writer.wait_closed()
                self.assertIn(expected, response.split(b"\r\n")[0])
                self.assertNotIn(b"private-fixture", response)
        self.assertNotIn("private-fixture", " ".join(logs.output))


class GSClient:
    """Real RSA/Blowfish client for protocol integration tests, no crypto mocks."""
    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer
        self.key = bytes(range(16))

    async def send(self, kind, fields=None, *, encrypted=False):
        body = b"" if fields is None else data.encode(fields)
        body = crypto.encrypt_payload(self.key, body) if encrypted else gsxor.encrypt(body)
        self.writer.write(GSHeader(HEADER_SIZE + len(body), 2 if encrypted else 0, 1, kind, 1, 2).encode() + body)
        await self.writer.drain()

    async def receive(self):
        header, body = await asyncio.wait_for(read_frame(self.reader), 3)
        return header, data.decode(gsxor.decrypt(body)) if body else []

    async def handshake(self, private):
        public = private.public_key().public_numbers()
        blob = crypto.GSPublicKey(512, public.n, public.e).encode()
        await self.send(0xdb, ["1", ["1", str(len(blob)), blob]])
        _, fields = await self.receive()
        server = crypto.GSPublicKey.decode(fields[1][2])
        encrypted = server.encrypt(self.key)
        await self.send(0xdb, ["2", ["1", str(len(encrypted)), encrypted]])
        _, fields = await self.receive()
        server_key = private.decrypt(fields[1][2], padding.PKCS1v15())
        if len(server_key) != 16:
            raise AssertionError("wrong server cipher-key size")


class MultiGameServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_database_authenticates_both_games_but_handoffs_do_not_cross_titles(self):
        with TemporaryDirectory() as directory:
            # Reserve distinct ports until configuration is ready; no public listeners.
            reservations = []
            try:
                for _ in range(7):
                    sock = socket.socket()
                    sock.bind(("127.0.0.1", 0))
                    reservations.append(sock)
                ports = [sock.getsockname()[1] for sock in reservations]
                env = {"TUBISOFT_ADVERTISE_IP": "127.0.0.1", "TUBISOFT_BIND_IP": "127.0.0.1",
                       "TUBISOFT_STATE_DIR": directory, "TUBISOFT_GAMES": "xiii,gr2",
                       "TUBISOFT_HTTP_PORT": str(ports[6])}
                for prefix, selected in (("TUBISOFT_", ports[:3]), ("TUBISOFT_GR2_", ports[3:6])):
                    for role, port in zip(("ROUTER", "LAUNCHER", "NAT"), selected):
                        env[prefix + role + "_PORT"] = str(port)
                args = service.configuration(env)
            finally:
                for sock in reservations:
                    sock.close()
            task = asyncio.create_task(service.serve(args))
            clients = []
            try:
                for attempt in range(100):
                    if task.done():
                        await task
                    try:
                        reader, writer = await asyncio.open_connection("127.0.0.1", ports[6])
                        writer.write(b"GET /healthz HTTP/1.0\r\n\r\n")
                        await writer.drain()
                        self.assertIn(b"200 OK", await asyncio.wait_for(reader.read(), 2))
                        writer.close()
                        await writer.wait_closed()
                        break
                    except ConnectionRefusedError:
                        if attempt == 99:
                            raise
                        await asyncio.sleep(0.01)
                private = router.load_key(args.private_key)

                async def connect(port):
                    client = GSClient(*await asyncio.open_connection("127.0.0.1", port))
                    clients.append(client)
                    await client.handshake(private)
                    return client

                xiii = await connect(ports[0])
                await xiii.send(1, ["1.0", "SharedFixture", "fixture-only", "", "", "", ""], encrypted=True)
                header, fields = await xiii.receive()
                self.assertEqual((header.message_type, fields), (0x26, [b"\x01"]))
                gr2 = await connect(ports[3])
                await gr2.send(0x66, ["SHAREDFIXTURE", "fixture-only", "1.0", b"\0"], encrypted=True)
                header, fields = await gr2.receive()
                self.assertEqual((header.message_type, fields), (0x26, [b"\x66"]))
                await gr2.send(0x5d)
                _, fields = await gr2.receive()
                self.assertEqual(fields, [b"\x5d", ["127.0.0.1", ports[3].to_bytes(4, "little")]])
                # Same account/IP cannot redeem GR2's handoff at XIII's listener.
                wrong = await connect(ports[0])
                await wrong.send(0x4d, ["SharedFixture"])
                self.assertEqual(await asyncio.wait_for(wrong.reader.read(), 2), b"")
                wait = await connect(ports[3])
                await wait.send(0x4d, ["SharedFixture"])
                header, fields = await wait.receive()
                self.assertEqual((header.message_type, fields), (0x26, [b"\x4d"]))
                await wait.send(0x3a)
                header, fields = await wait.receive()
                self.assertEqual((header.message_type, fields), (0x3a, []))
                # Unimplemented GR2 lobby operations never receive XIII's records.
                await wait.send(0xd1, ["21", []])
                self.assertEqual(await asyncio.wait_for(wait.reader.read(), 2), b"")
                with closing(sqlite3.connect(args.account_db)) as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0], 1)
                self.assertTrue(await asyncio.to_thread(accounts.verify_account, args.account_db,
                                                       "SharedFixture", "fixture-only"))
                self.assertEqual(list(Path(directory).glob("*.sqlite3")), [args.account_db])
            finally:
                for client in clients:
                    client.writer.close()
                    await client.writer.wait_closed()
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
