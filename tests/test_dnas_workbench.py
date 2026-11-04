"""Synthetic fixtures only; no retail captures, title data, or expected secrets."""
import hashlib
import importlib.util
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import unittest

spec = importlib.util.spec_from_file_location("dnas_workbench", Path(__file__).resolve().parents[1] / "tools/dnas_workbench.py")
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


class DNASWorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.request = bytes((i * 73 + 11) & 255 for i in range(308))
        self.plain = bytes((i * 19 + 7) & 255 for i in range(328))

    def test_transport_matches_synthetic_known_answer_from_existing_replay_service(self):
        wire = bench.transport(self.plain, self.request)
        self.assertEqual(hashlib.sha256(wire).hexdigest(),
                         "922e35e319ff80522352dbf6ca727eeca367532c2f4e6afd7d79847aa38575f7")
        self.assertEqual(wire[:0x28], self.plain[:0x28])
        self.assertEqual(bench.transport(wire, self.request, decode=True), self.plain)

    def test_request_binding_changes_the_session_window(self):
        other = bytearray(self.request)
        other[0x80] ^= 0xff
        self.assertNotEqual(bench.transport(self.plain, self.request), bench.transport(self.plain, bytes(other)))
        # The wire packet cannot be unwrapped correctly against another request.
        self.assertNotEqual(bench.transport(bench.transport(self.plain, self.request), bytes(other), decode=True), self.plain)

    def test_candidate_requires_an_explicit_value_and_changes_only_that_field(self):
        value = bytes(range(20))
        result = bench.candidate(self.plain, value)
        self.assertEqual(result[:0x3c], self.plain[:0x3c])
        self.assertEqual(result[0x3c:0x50], value)
        self.assertEqual(result[0x50:], self.plain[0x50:])
        report = bench.compare(self.plain, result)
        self.assertEqual(report["changed_ranges"], [[0x3c, 0x50]])
        self.assertFalse(report["tsfp_check_field_equal"])
        self.assertTrue(report["session_field_equal"])

    def test_wrong_lengths_and_unknown_overlay_builds_are_refused(self):
        for length in (0, 40, 327, 329):
            with self.subTest(length=length), self.assertRaises(ValueError):
                bench.transport(bytes(length), self.request)
        for operation in (lambda: bench.request_identity(bytes(307)),
                          lambda: bench.candidate(self.plain, bytes(19)),
                          lambda: bench.recover_overlay(b"unknown-build", "gr2-usa")):
            with self.assertRaises(ValueError):
                operation()

    def test_outputs_are_private_and_cannot_overwrite_a_working_packet(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "private" / "candidate.raw"
            report = bench.write_private(path, self.plain)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(report["bytes"], 328)
            with self.assertRaises(FileExistsError):
                bench.write_private(path, b"replacement")
            self.assertEqual(path.read_bytes(), self.plain)

    @staticmethod
    def rom():
        raw = bytearray(128)
        for index, (name, size) in enumerate(((b"RESET", 0), (b"ROMDIR", 80), (b"EXTINFO", 16), (b"MODULE", 20))):
            struct.pack_into("<10sHI", raw, index * 16, name, 0, size)
        raw[96:116] = b"\x7fELF" + bytes(range(16))
        return raw

    def test_iop_module_directory_extracts_only_elfs_and_checks_bounds(self):
        raw = self.rom()
        self.assertEqual(bench.rom_modules(bytes(raw)), [("MODULE", b"\x7fELF" + bytes(range(16)))])
        struct.pack_into("<I", raw, 3 * 16 + 12, 1000)
        with self.assertRaises(ValueError):
            bench.rom_modules(bytes(raw))

    def test_iop_module_names_cannot_escape_the_output_directory(self):
        raw = self.rom()
        raw[48:58] = b"../BAD\0\0\0\0"
        with self.assertRaises(ValueError):
            bench.rom_modules(bytes(raw))
