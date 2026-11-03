import struct
import time
import unittest

from ubisoft import data, gsxor
from ubisoft.frame import GSHeader, HEADER_SIZE
from ubisoft.rooms import RoomRegistry
from ubisoft.srp_probe import HEADER, WINDOW, ACK, FIN, IDENT, SYN, Probe, Session, checksum, finish_datagram, syn_reply


class SynProbeTests(unittest.TestCase):
    def test_outbound_datagrams_keep_checksum_loads_aligned_without_delivering_padding_as_data(self):
        for seed in (0, 0x80, 0x8080, 0xffff):
            for length in range(1, 18):
                with self.subTest(seed=seed, length=length):
                    payload = bytes(range(length))
                    original = HEADER.pack(seed, 0x1234, length, IDENT | ACK, 1, 0) + payload
                    packet = finish_datagram(original)
                    self.assertEqual(len(packet) % 2, 0)
                    self.assertEqual(HEADER.unpack_from(packet)[1:], HEADER.unpack_from(original)[1:])
                    declared = HEADER.unpack_from(packet)[2]
                    self.assertEqual(packet[HEADER.size:HEADER.size + declared], payload)
                    self.assertEqual(packet[HEADER.size + declared:], b"\0" if length & 1 else b"")
                    self.assertEqual(HEADER.unpack_from(packet)[0], checksum(seed.to_bytes(2, "little") + packet[2:]))

    def test_checksum_matches_signed_byte_and_32_bit_folding_in_client(self):
        # MIPS lb at 0x01d520d8 sign-extends the odd leading byte;
        # addu then srl implement 32-bit wrap and unsigned folding.
        self.assertEqual(checksum(b"\x80\x00\x01"), 0xff7f)
        self.assertEqual(checksum(b"\x80"), 0x007f)
        self.assertEqual(checksum(b"\x7f\x00\x01"), 0xfe80)

    def test_candidate_syn_reply_has_expected_window_and_checksum(self):
        packet = HEADER.pack(0, 0, 8, IDENT | SYN, 7, 0) + WINDOW.pack(10, 0x1234, 0, 536)
        reply = syn_reply(packet)
        checksum_value, signature, size, flags, seq, ack = HEADER.unpack_from(reply)
        self.assertEqual((signature, size, flags, seq, ack), (0x1234, 8, IDENT | SYN | ACK, 0, 7))
        self.assertEqual(WINDOW.unpack_from(reply, HEADER.size), (10, 2, 0, 536))
        self.assertNotEqual(checksum_value, 0)
        self.assertEqual(checksum(reply), 0)

    def test_rejects_truncated_and_non_syn_packets(self):
        with self.assertRaises(ValueError):
            syn_reply(b"short")
        packet = HEADER.pack(0, 0, 8, IDENT | ACK, 0, 0) + WINDOW.pack(0, 0, 0, 0)
        with self.assertRaises(ValueError):
            syn_reply(packet)


class FakeTransport:
    def __init__(self):
        self.sent = []

    def sendto(self, packet, peer):
        self.sent.append((packet, peer))

    def get_extra_info(self, name):
        return ("192.0.2.1", 30000) if name == "sockname" else None


class DatagramFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_data_sequence_passes_window_size_and_wraps_at_twice_the_window(self):
        # Client 0x01d52ee0 shifts the SYN-ACK's window left once for its
        # receive ring. Live ACKs ceased when the old implementation sent
        # sequence zero after nine instead of continuing at ten.
        probe = Probe({}, RoomRegistry())
        transport = FakeTransport()
        probe.transport = transport
        session = Session(0x1234, 0, next_segment=9)
        sequences = []
        for _ in range(12):
            probe.send_message(("192.0.2.2", 1024), session, 0, b"frame")
            sequences.append(HEADER.unpack_from(transport.sent[-1][0])[4])
        self.assertEqual(sequences, list(range(9, 20)) + [0])

    async def test_host_notification_retries_stop_on_ack_without_replacing_cached_request_reply(self):
        registry = RoomRegistry()
        fields = ["12", "1", ["launcher", "1", "Example", "XIIIPS2US", "6", "16", "0",
                              b"info", b"\0", "", "1.0", "XIIIPS21.0", "8208",
                              "192.0.2.2", "7777", b""]]
        room = registry.register("host", "192.0.2.2", fields)
        registry.activate(room.room_id, "host", room.peer_ip)
        probe = Probe({}, registry)
        transport = FakeTransport()
        probe.connection_made(transport)
        self.addCleanup(probe.connection_lost, None)
        peer = (room.peer_ip, 1024)
        session = Session(0x1234, 0, next_segment=19, last_segment=7,
                          last_reply=b"request-reply", room=room)
        probe.sessions[peer] = session
        self.assertFalse(probe.member_info(room, "host", room.peer_ip, b"1234", new=True))
        self.assertTrue(probe.member_info(room, "guest", "192.0.2.3", (64510).to_bytes(4, "little"), new=True))
        packet = transport.sent[-1][0]
        self.assertEqual(session.next_segment, 0)
        self.assertEqual((session.last_segment, session.last_reply), (7, b"request-reply"))
        session.notifications[19] = (packet, 1, time.monotonic() - 2)
        probe.retries.cancel()
        probe.retry_notifications()
        self.assertEqual(transport.sent, [(packet, peer), (packet, peer)])
        probe.datagram_received(HEADER.pack(0, 0x1234, 0, IDENT | ACK, 0xffff, 19), peer)
        self.assertEqual(session.notifications, {})
        probe.retries.cancel()
        probe.retry_notifications()
        self.assertEqual(len(transport.sent), 2)

    async def test_empty_reliable_segment_gets_ack_without_consuming_data_sequence(self):
        probe = Probe({}, RoomRegistry())
        transport = FakeTransport()
        probe.connection_made(transport)
        peer = ("192.0.2.2", 1024)
        session = Session(0x1234, 0, next_segment=7, last_segment=5,
                          last_reply=b"cached-data-response", last_seen=time.monotonic())
        probe.sessions[peer] = session
        packet = HEADER.pack(0, 0x1234, 0, IDENT, 2, 0xffff)
        probe.datagram_received(packet, peer)
        self.assertEqual(len(transport.sent), 1)
        ack, destination = transport.sent[0]
        self.assertEqual(destination, peer)
        self.assertEqual(HEADER.unpack(ack)[1:], (0x1234, 0, IDENT | ACK, 0xffff, 2))
        self.assertEqual(checksum(ack), 0)
        probe.datagram_received(packet, peer)
        self.assertEqual(transport.sent[-1][0], ack)
        self.assertEqual(session.next_segment, 7)
        self.assertEqual((session.last_segment, session.last_reply), (5, b"cached-data-response"))
        count = len(transport.sent)
        probe.datagram_received(HEADER.pack(0, 0x1234, 0, IDENT | ACK, 0xffff, 7), peer)
        self.assertEqual(len(transport.sent), count)
        probe.connection_lost(None)

    async def test_padded_host_login_activates_and_cleans_room(self):
        registry = RoomRegistry()
        fields = ["12", "1", ["launcher", "1", "Example", "XIIIPS2US", "6", "16", "0",
                              b"2?17?20?10?N?8:7777", b"\0", "", "1.0", "XIIIPS21.0",
                              "8208", "192.0.2.2", "7777", b""]]
        room = registry.register("user", "192.0.2.2", fields)
        pending = {("192.0.2.2", "user"): time.monotonic() + 60}
        probe = Probe(pending, registry)
        transport = FakeTransport()
        probe.connection_made(transport)
        peer = ("192.0.2.2", 1024)
        syn = HEADER.pack(0, 0, 8, IDENT | SYN, 0, 0) + WINDOW.pack(10, 0x1234, 0, 536)
        probe.datagram_received(syn, peer)
        encoded = gsxor.encrypt(data.encode(["user", str(room.room_id)]))
        frame = GSHeader(HEADER_SIZE + len(encoded), 0, 1, 0xd2, 4, 2).encode() + encoded
        packet = HEADER.pack(0, 0, len(frame), IDENT, 0, 0) + frame
        probe.datagram_received(packet + bytes(548 - len(packet)), peer)
        self.assertTrue(room.active)
        response = transport.sent[-1][0]
        self.assertEqual(checksum(response), 0)
        response_header = GSHeader.decode(response[HEADER.size:HEADER.size + HEADER_SIZE])
        self.assertEqual(response_header.message_type, 0x26)
        self.assertEqual(data.decode(gsxor.decrypt(response[HEADER.size + HEADER_SIZE:HEADER.size + response_header.size])),
                         ["210", ["1", str(room.room_id)]])
        self.assertEqual(len(registry.children()), 1)
        probe.datagram_received(HEADER.pack(0, 0, 0, IDENT | FIN, 1, 1), peer)
        self.assertEqual(registry.children(), [])
        probe.connection_lost(None)

    async def test_host_match_and_score_updates_are_acknowledged_for_owned_room(self):
        registry = RoomRegistry()
        fields = ["12", "1", ["launcher", "1", "Example", "XIIIPS2US", "6", "16", "0",
                              b"description:7777", b"\0", "", "1.0", "XIIIPS21.0",
                              "8208", "192.0.2.2", "7777", b""]]
        room = registry.register("user", "192.0.2.2", fields)
        probe = Probe({("192.0.2.2", "user"): time.monotonic() + 60}, registry)
        transport = FakeTransport()
        probe.connection_made(transport)
        peer = ("192.0.2.2", 1024)
        probe.datagram_received(HEADER.pack(0, 0, 8, IDENT | SYN, 0, 0)
                                + WINDOW.pack(10, 0x1234, 0, 536), peer)

        def request(segment, message_type, payload):
            encoded = gsxor.encrypt(data.encode(payload))
            frame = GSHeader(HEADER_SIZE + len(encoded), 0, 1, message_type, 4, 2).encode() + encoded
            return HEADER.pack(0, 0, len(frame), IDENT, segment, 0) + frame

        probe.datagram_received(request(0, 0xd2, ["user", str(room.room_id)]), peer)
        for segment, subtype, values in ((1, "17", [str(room.room_id), "0"]),
                                          (2, "31", [str(room.room_id), "1024", b"player=5"]),
                                          (3, "45", [str(room.room_id)])):
            packet = request(segment, 0xd1, [subtype, values])
            probe.datagram_received(packet, peer)
            response = transport.sent[-1][0]
            header = GSHeader.decode(response[HEADER.size:HEADER.size + HEADER_SIZE])
            self.assertEqual(header.message_type, 0x26)
            self.assertEqual(data.decode(gsxor.decrypt(response[HEADER.size + HEADER_SIZE:HEADER.size + header.size])),
                             [subtype, [str(room.room_id)]])
            self.assertEqual(checksum(response), 0)
            count = len(transport.sent)
            probe.datagram_received(packet, peer)
            self.assertEqual(len(transport.sent), count + 1)
            self.assertEqual(transport.sent[-1][0], response)
        self.assertEqual(room.additional_info, b"player=5")
        count = len(transport.sent)
        probe.datagram_received(request(4, 0xd1, ["31", ["9999", "1024", b"forged"]]), peer)
        self.assertEqual(len(transport.sent), count)
        self.assertEqual(room.additional_info, b"player=5")
        probe.connection_lost(None)


if __name__ == "__main__":
    unittest.main()
