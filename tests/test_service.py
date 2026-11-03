import asyncio
import logging
from pathlib import Path
import tempfile
import unittest

from ubisoft.access import AccessPolicy
from ubisoft.bootstrap import handle
from ubisoft.service import PrivacyFormatter, configuration, ensure_key
from ubisoft.router import load_key
from ubisoft.frame import GSHeader, read_frame


class ConfigurationTests(unittest.TestCase):
    def test_public_beta_accepts_any_source_without_tester_configuration(self):
        args = configuration({"TUBISOFT_ADVERTISE_IP": "192.0.2.10"})
        self.assertTrue(args.access_policy.acquire("198.51.100.22"))
        self.assertTrue(args.access_policy.acquire("203.0.113.32"))
        self.assertEqual(args.nat_allowed_cidr, "0.0.0.0/0")

    def test_reachable_advertisement_and_explicit_access_are_required(self):
        for env in ({}, {"TUBISOFT_ADVERTISE_IP": "0.0.0.0", "TUBISOFT_ALLOWED_CIDRS": "127.0.0.0/8"},
                    {"TUBISOFT_ADVERTISE_IP": "192.0.2.10", "TUBISOFT_ALLOWED_CIDRS": ""}):
            with self.assertRaises((KeyError, ValueError)):
                configuration(env)
        args = configuration({"TUBISOFT_ADVERTISE_IP": "192.0.2.10", "TUBISOFT_ALLOWED_CIDRS": "192.0.2.0/24,198.51.100.3/32"})
        self.assertEqual((args.bind, args.advertise_ip), ("0.0.0.0", "192.0.2.10"))

    def test_access_connection_and_authentication_limits(self):
        policy = AccessPolicy("192.0.2.0/24", per_ip=1)
        self.assertFalse(policy.acquire("198.51.100.2"))
        self.assertTrue(policy.acquire("192.0.2.2"))
        self.assertFalse(policy.acquire("192.0.2.2"))
        policy.release("192.0.2.2")
        self.assertTrue(policy.acquire("192.0.2.2"))
        self.assertTrue(all(policy.allow_authentication("192.0.2.2") for _ in range(10)))
        self.assertFalse(policy.allow_authentication("192.0.2.2"))

    def test_log_identifiers_hide_addresses_and_are_ephemeral(self):
        record = logging.LogRecord("test", logging.INFO, "fixture", 1, "peer=%s", ("192.0.2.2",), None)
        first = PrivacyFormatter()
        self.assertNotIn("192.0.2.2", first.format(record))
        self.assertEqual(first.format(record), first.format(record))
        self.assertNotEqual(first.format(record), PrivacyFormatter().format(record))

    def test_key_is_generated_privately_and_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "router-private.pem"
            ensure_key(path)
            original = path.read_bytes()
            self.assertEqual(load_key(path).key_size, 512)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            ensure_key(path)
            self.assertEqual(path.read_bytes(), original)


class BootstrapTests(unittest.IsolatedAsyncioTestCase):
    async def test_router_frame_limit_rejects_length_before_reading_body(self):
        reader = asyncio.StreamReader()
        reader.feed_data(GSHeader(70000, 0, 1, 0xdb, 8, 2).encode())
        with self.assertRaises(ValueError):
            await read_frame(reader, maximum_size=65535)

    async def test_profile_dispatch_and_health(self):
        server = await asyncio.start_server(lambda r, w: handle(r, w, b"fixture-bootstrap"), "127.0.0.1", 0)
        self.addAsyncCleanup(server.wait_closed)
        self.addCleanup(server.close)
        for target, status, body in (("/gsinit.php?dp=XIIIPS2US", b"200", b"fixture-bootstrap"),
                                     ("/gsinit.php?dp=OTHER", b"404", b"Not found"),
                                     ("/healthz", b"200", b"ok\n")):
            reader, writer = await asyncio.open_connection("127.0.0.1", server.sockets[0].getsockname()[1])
            writer.write(f"GET {target} HTTP/1.0\r\n\r\n".encode())
            await writer.drain()
            response = await reader.read()
            writer.close()
            await writer.wait_closed()
            self.assertIn(status, response.split(b"\r\n")[0])
            self.assertIn(body, response)
