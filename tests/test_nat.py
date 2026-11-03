import ipaddress
import time
import unittest
from unittest.mock import patch

from ubisoft import data, gsxor
from ubisoft.frame import GSHeader, HEADER_SIZE
from ubisoft.nat import Discovery, SESSION_SECONDS, RETRY_SECONDS, MAX_RETRIES
from ubisoft.srp_probe import HEADER, WINDOW, ACK, IDENT, SYN, checksum


class Transport:
    def __init__(self):
        self.sent = []

    def get_extra_info(self, name):
        return ("192.0.2.1", 30002) if name == "sockname" else None

    def sendto(self, packet, peer):
        self.sent.append((packet, peer))


def control_request(request_id="7", segment=0):
    payload = gsxor.encrypt(data.encode(["1", [request_id, "XIIIPS2US", "1.0", "XIIIPS21.0"]]))
    frame = GSHeader(HEADER_SIZE + len(payload), 0, 1, 0xdd, 8, 2).encode() + payload
    return HEADER.pack(0, 0x1234, len(frame), IDENT, segment, 0) + frame


def fields(packet):
    header = GSHeader.decode(packet[HEADER.size:HEADER.size + HEADER_SIZE])
    return header, data.decode(gsxor.decrypt(packet[HEADER.size + HEADER_SIZE:HEADER.size + header.size]))


def checksum_valid(packet):
    # XIII saves the received checksum, overwrites that word with its negotiated
    # seed, then recalculates and compares (0x01d52384). An odd-length packet
    # does not have the usual checksum(full_packet) == 0 invariant.
    received = HEADER.unpack_from(packet)[0]
    return received == checksum(b"\0\0" + packet[2:])


class NatTests(unittest.IsolatedAsyncioTestCase):
    def start(self):
        helper = Discovery("192.0.2.0/24")
        transport = Transport()
        helper.connection_made(transport)
        self.addCleanup(helper.connection_lost, None)
        return helper, transport

    def handshake(self, helper, peer):
        helper.datagram_received(HEADER.pack(0, 0, 8, IDENT | SYN, 0, 0)
                                 + WINDOW.pack(10, 0x1234, 0, 536), peer)

    async def test_odd_sized_nat_reply_is_aligned_without_changing_its_token_or_declared_length(self):
        helper, transport = self.start()
        peer = ("192.0.2.2", 1026)
        self.handshake(helper, peer)
        token = b"\xde\xad\xbe\xef"
        with patch("ubisoft.nat.secrets.token_bytes", return_value=token):
            helper.datagram_received(control_request(), peer)
        packet = transport.sent[-1][0]
        header, body = fields(packet)
        self.assertEqual(HEADER.unpack_from(packet)[2], header.size)
        self.assertEqual(HEADER.size + header.size, 45)
        self.assertEqual(len(packet), 46)
        self.assertEqual(packet[-1:], b"\0")
        self.assertEqual(body, ["2", ["7", str(int.from_bytes(token, "big")), "30002"]])
        self.assertTrue(checksum_valid(packet))
        helper.datagram_received(token, (peer[0], 7777))
        self.assertEqual(len(transport.sent[-1][0]) % 2, 0)

    async def test_lost_port_and_address_replies_are_retried_identically_until_acknowledged(self):
        helper, transport = self.start()
        peer = ("192.0.2.2", 1026)
        clock = [time.monotonic()]
        with patch("ubisoft.nat.time.monotonic", side_effect=lambda: clock[0]):
            self.handshake(helper, peer)
            helper.datagram_received(control_request(), peer)
            port_packet = transport.sent[-1]
            count = len(transport.sent)
            helper.retry_pending()
            self.assertEqual(len(transport.sent), count)
            clock[0] += RETRY_SECONDS
            helper.retry_pending()
            self.assertEqual(transport.sent[count:], [port_packet])
            sequence = HEADER.unpack_from(port_packet[0])[4]
            helper.datagram_received(HEADER.pack(0, 0x1234, 0, IDENT | ACK, 0xffff, sequence), peer)
            count = len(transport.sent)
            clock[0] += RETRY_SECONDS
            helper.retry_pending()
            self.assertEqual(len(transport.sent), count)

            token = int(fields(port_packet[0])[1][1][1]).to_bytes(4, "big")
            helper.datagram_received(token, (peer[0], 7777))
            address_packet = transport.sent[-1]
            count = len(transport.sent)
            clock[0] += RETRY_SECONDS
            helper.retry_pending()
            self.assertEqual(transport.sent[count:], [address_packet])
            sequence = HEADER.unpack_from(address_packet[0])[4]
            helper.datagram_received(HEADER.pack(0, 0x1234, 0, IDENT | ACK, 0xffff, sequence), peer)
            count = len(transport.sent)
            clock[0] += RETRY_SECONDS
            helper.retry_pending()
            self.assertEqual(len(transport.sent), count)

    async def test_retries_are_bounded_and_do_not_keep_dead_or_removed_sessions_alive(self):
        helper, transport = self.start()
        peer = ("192.0.2.2", 1026)
        clock = [time.monotonic()]
        with patch("ubisoft.nat.time.monotonic", side_effect=lambda: clock[0]):
            self.handshake(helper, peer)
            helper.datagram_received(control_request(), peer)
            original = transport.sent[-1]
            last_seen = helper.sessions[peer].last_seen
            count = len(transport.sent)
            for _ in range(MAX_RETRIES + 2):
                clock[0] += RETRY_SECONDS
                helper.retry_pending()
            self.assertEqual(transport.sent[count:], [original] * MAX_RETRIES)
            self.assertEqual(helper.sessions[peer].last_seen, last_seen)

            self.handshake(helper, peer)
            helper.datagram_received(control_request(), peer)
            count = len(transport.sent)
            clock[0] += SESSION_SECONDS + 1
            helper.retry_pending()
            self.assertEqual(len(transport.sent), count)
            helper.remove(peer)
            helper.retry_pending()
            self.assertEqual(len(transport.sent), count)

    async def test_correlated_game_probe_stops_port_retries_even_without_its_ack(self):
        helper, transport = self.start()
        peer = ("192.0.2.2", 1026)
        clock = [time.monotonic()]
        with patch("ubisoft.nat.time.monotonic", side_effect=lambda: clock[0]):
            self.handshake(helper, peer)
            helper.datagram_received(control_request(), peer)
            token = int(fields(transport.sent[-1][0])[1][1][1]).to_bytes(4, "big")
            helper.datagram_received(token, (peer[0], 7777))
            address_packet = transport.sent[-1]
            count = len(transport.sent)
            clock[0] += RETRY_SECONDS
            helper.retry_pending()
            self.assertEqual(transport.sent[count:], [address_packet])

    async def test_diagnostics_distinguish_unacknowledged_and_completed_lookups_without_logging_tokens(self):
        helper, transport = self.start()
        peer = ("192.0.2.2", 1026)
        token = b"\xde\xad\xbe\xef"
        with self.assertLogs("ubisoft.nat", level="INFO") as captured, patch("ubisoft.nat.secrets.token_bytes", return_value=token):
            self.handshake(helper, peer)
            helper.datagram_received(control_request(), peer)
            helper.remove(peer, reason="idle-timeout")
            self.handshake(helper, peer)
            helper.datagram_received(control_request(), peer)
            sequence = HEADER.unpack_from(transport.sent[-1][0])[4]
            helper.datagram_received(HEADER.pack(0, 0x1234, 0, IDENT | ACK, 0xffff, sequence), peer)
            helper.datagram_received(token, (peer[0], 7777))
            sequence = HEADER.unpack_from(transport.sent[-1][0])[4]
            helper.datagram_received(HEADER.pack(0, 0x1234, 0, IDENT | ACK, 0xffff, sequence), peer)
            helper.remove(peer)
        log = "\n".join(captured.output)
        self.assertIn("subtype=2 request=7", log)
        self.assertIn("port_acks=0 game_endpoints=0 address_acks=0", log)
        self.assertIn("NAT port reply acknowledged", log)
        self.assertIn("NAT address reply acknowledged", log)
        self.assertIn("port_acks=1 game_endpoints=1 address_acks=1", log)
        for private_value in (repr(token), token.hex(), str(int.from_bytes(token, "big"))):
            self.assertNotIn(private_value, log)

    async def test_reports_game_socket_endpoint_only_after_its_correlated_probe(self):
        helper, transport = self.start()
        control_peer = ("192.0.2.2", 1026)
        game_peer = (control_peer[0], 7777)
        self.handshake(helper, control_peer)
        request = control_request()
        helper.datagram_received(request, control_peer)
        self.assertEqual(len(transport.sent), 2)
        response, destination = transport.sent[-1]
        header, body = fields(response)
        self.assertEqual((header.message_type, header.sender, header.receiver), (0xdd, 2, 8))
        self.assertEqual(body[0], "2")
        self.assertEqual((body[1][0], body[1][2]), ("7", "30002"))
        self.assertTrue(checksum_valid(response))
        token = int(body[1][1]).to_bytes(4, "big")
        self.assertEqual(destination, control_peer)
        helper.datagram_received(token, ("192.0.2.3", 7777))
        self.assertEqual(len(transport.sent), 2)
        helper.datagram_received(token, game_peer)
        self.assertEqual(transport.sent[-2], (token, game_peer))
        address_packet, destination = transport.sent[-1]
        _, body = fields(address_packet)
        self.assertEqual(body[0], "3")
        self.assertEqual(body[1][0], "7")
        self.assertEqual(ipaddress.IPv4Address(int(body[1][1]).to_bytes(4, "little")),
                         ipaddress.IPv4Address(game_peer[0]))
        self.assertEqual(body[1][2], "7777")
        self.assertEqual(destination, control_peer)
        self.assertTrue(checksum_valid(address_packet))
        # An unacknowledged lookup completion is retried with the same SRP
        # sequence; once ACKed, periodic probes only keep the game port open.
        helper.datagram_received(token, game_peer)
        self.assertEqual(transport.sent[-1], (address_packet, control_peer))
        sequence = HEADER.unpack_from(address_packet)[4]
        helper.datagram_received(HEADER.pack(0, 0x1234, 0, IDENT | ACK, 0xffff, sequence), control_peer)
        count = len(transport.sent)
        helper.datagram_received(token, game_peer)
        self.assertEqual(transport.sent[count:], [(token, game_peer)])
        # A retransmitted original request replays the original replies.
        count = len(transport.sent)
        helper.datagram_received(request, control_peer)
        self.assertEqual(transport.sent[count:], [(response, control_peer), (address_packet, control_peer)])

    async def test_same_request_id_on_two_pcs_stays_separate_and_stale_tokens_expire(self):
        helper, transport = self.start()
        peers = [("192.0.2.2", 1026), ("192.0.2.3", 1026)]
        tokens = []
        for peer in peers:
            self.handshake(helper, peer)
            helper.datagram_received(control_request(), peer)
            _, body = fields(transport.sent[-1][0])
            tokens.append(int(body[1][1]).to_bytes(4, "big"))
        self.assertNotEqual(tokens[0], tokens[1])
        count = len(transport.sent)
        helper.datagram_received(tokens[0], (peers[1][0], 8888))
        self.assertEqual(len(transport.sent), count)
        helper.datagram_received(tokens[1], (peers[1][0], 8888))
        self.assertEqual(transport.sent[-1][1], peers[1])
        self.assertEqual(fields(transport.sent[-1][0])[1][1][2], "8888")
        helper.sessions[peers[0]].last_seen = time.monotonic() - SESSION_SECONDS - 1
        count = len(transport.sent)
        helper.datagram_received(tokens[0], (peers[0][0], 7777))
        self.assertEqual(len(transport.sent), count)
        helper.remove(peers[0])
        self.assertNotIn(tokens[0], helper.tokens)
        helper.datagram_received(b"junk", ("198.51.100.1", 7777))
        self.assertEqual(len(transport.sent), count)


if __name__ == "__main__":
    unittest.main()
