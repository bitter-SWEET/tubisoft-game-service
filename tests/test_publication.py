from pathlib import Path
import tempfile
import unittest

from tools.publication_audit import inspect


class PublicationTests(unittest.TestCase):
    def test_detects_private_artifacts_and_sensitive_text_without_returning_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root / "fixture.txt"
            samples = (("-----BEGIN " + "PRIVATE KEY-----", "private-key material"),
                       ("/home/" + "example/checkout", "personal home path"),
                       ("sample" + "@" + "example.net", "email address"))
            for content, label in samples:
                fixture.write_text(content)
                self.assertIn((1, label), inspect(fixture))
                self.assertNotIn(content, str(inspect(fixture)))
            artifact = root / "accounts.sqlite3"
            artifact.write_bytes(b"fixture")
            self.assertEqual(inspect(artifact), [(0, "private/runtime artifact filename")])
            fixture.write_text("Use documentation address 192.0.2.10 and loopback 127.0.0.1.")
            self.assertEqual(inspect(fixture), [])
