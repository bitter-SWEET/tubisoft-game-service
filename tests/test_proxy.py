"""Proxy session boundaries and native GR2 empty-ranking records."""
import copy
import unittest
from unittest.mock import patch

from ubisoft import proxy
from ubisoft.games.registry import GR2, XIII


def query():
    return ["1281", "17", ["1", ["900", GR2.product, "0", "1",
                               ["4", ["Fixture"]], [[], [], []]]]]


class ProxyTests(unittest.TestCase):
    def test_proxy_login_redeems_only_the_selected_accounts_peer_and_version_grant(self):
        handoffs = proxy.Handoffs()
        self.assertFalse(handoffs.consume_login("192.0.2.1", "first", GR2.sdk_version))
        for username in ("first", "second"):
            handoffs.authorize_login("192.0.2.1", username, GR2.sdk_version)
        for peer, username, version in (("192.0.2.2", "first", GR2.sdk_version),
                                        ("192.0.2.1", "unselected", GR2.sdk_version),
                                        ("192.0.2.1", "first", "a-password")):
            self.assertFalse(handoffs.consume_login(peer, username, version))
        self.assertTrue(handoffs.consume_login("192.0.2.1", "FIRST", GR2.sdk_version))
        self.assertFalse(handoffs.consume_login("192.0.2.1", "first", GR2.sdk_version))
        self.assertTrue(handoffs.consume_login("192.0.2.1", "second", GR2.sdk_version))

    def test_proxy_login_grants_expire_and_share_the_ticket_capacity_bound(self):
        with patch.object(proxy.time, "monotonic", return_value=100) as clock:
            handoffs = proxy.Handoffs(limit=1, lifetime=5)
            handoffs.authorize_login("192.0.2.1", "first", GR2.sdk_version)
            with self.assertRaises(ValueError):
                handoffs.authorize_login("192.0.2.1", "second", GR2.sdk_version)
            with self.assertRaises(ValueError):
                handoffs.issue("192.0.2.1", "first")
            clock.return_value = 105
            self.assertFalse(handoffs.consume_login("192.0.2.1", "first", GR2.sdk_version))
            self.assertIsNotNone(handoffs.issue("192.0.2.1", "first"))

    def test_tickets_are_single_use_peer_bound_and_keep_accounts_at_one_ip_separate(self):
        handoffs = proxy.Handoffs()
        first = handoffs.issue("192.0.2.1", "first")
        second = handoffs.issue("192.0.2.1", "second")
        self.assertNotEqual(first, second)
        self.assertLessEqual(len(first.encode()), 15)
        self.assertIsNone(handoffs.redeem("192.0.2.2", first))
        self.assertEqual(handoffs.redeem("192.0.2.1", second), "second")
        self.assertEqual(handoffs.redeem("192.0.2.1", first), "first")
        self.assertIsNone(handoffs.redeem("192.0.2.1", first))

    def test_handoffs_expire_and_are_bounded(self):
        with patch.object(proxy.time, "monotonic", return_value=100) as clock:
            handoffs = proxy.Handoffs(limit=1, lifetime=5)
            expired = handoffs.issue("192.0.2.1", "first")
            with self.assertRaises(ValueError):
                handoffs.issue("192.0.2.1", "second")
            clock.return_value = 105
            self.assertIsNone(handoffs.redeem("192.0.2.1", expired))
            self.assertIsNotNone(handoffs.issue("192.0.2.1", "second"))

    def test_directory_does_not_accept_unadvertised_servers_or_other_services(self):
        directory = proxy.Directory(GR2, "192.0.2.1", 30010)
        for fields in (["2", ["1"]], [["3", "1"]], ["1", ["unknown", "0", "0"]],
                       ["1", ["ladderquery", "1", "0"]], ["1", [[], "0", "0"]]):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                directory.reply(fields)
        directory.reply(["1", ["ladderquery", "0", "0"]])
        for operation in ("3", "4"):
            self.assertIsNone(directory.reply([[operation, "1"]]))
        with self.assertRaises(ValueError):
            directory.reply(["2", ["999"]])
        with self.assertRaises(ValueError):
            directory.reply(["3", ["1"]])  # Native notification has one list.
        with self.assertRaises(ValueError):
            proxy.Directory(XIII, "192.0.2.1", 30000).reply(["1", ["ladderquery", "0", "0"]])

    def test_query_keeps_transport_id_and_returns_no_invented_rows(self):
        result = proxy.query_reply(GR2, query(), "fixture")
        self.assertEqual(result[:2], ["1281", "17"])
        table = result[2][1]
        # 0x004f4980 stores the first table integer at +8; 0x004f4de0
        # returns it as the completion ID. 900 is the application query,
        # while 17 is the independent transport request ID.
        self.assertEqual(table, ["1", ["900", "0", [], []]])
        invalid = []
        for index, value in ((0, "999"), (1, "-1"), (1, "4294967296"), (2, b"opaque")):
            candidate = query()
            candidate[index] = value
            invalid.append(candidate)
        for index, value in ((0, "-1"), (1, XIII.product), (2, "invalid"),
                             (3, "5"), (4, []), (5, [[], []])):
            candidate = copy.deepcopy(query())
            candidate[2][1][index] = value
            invalid.append(candidate)
        for candidate in invalid:
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                proxy.query_reply(GR2, candidate, "fixture")
        with self.assertRaises(ValueError):
            proxy.query_reply(XIII, query(), "fixture")
