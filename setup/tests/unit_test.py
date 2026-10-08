# /// script
# requires-python = ">=3.12"
# dependencies = ["tomli-w>=1", "pyyaml>=6", "snowballstemmer>=2.2"]
# [tool.uv]
# exclude-newer = "2026-10-01T00:00:00Z"
# ///
"""Unit tests of the parts where a mistake loses project data or misleads the user: managed-block
markers, versions and migrations, update classification, the secret scanner, resource URLs.

    TB_ROOT=. payload/modules/core/Toolbox/tb run setup/tests/unit_test.py
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import os  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402
from pathlib import Path  # noqa: E402

TEMPLATE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(TEMPLATE_ROOT / "setup"))
sys.path.insert(0, str(TEMPLATE_ROOT / "payload" / "modules" / "core" / "Toolbox" / "agentic"))

import installer_lib as il  # noqa: E402
import update  # noqa: E402
import resources  # noqa: E402
import secret_scan  # noqa: E402
import update_cmd  # noqa: E402

AGENTS = "# Demo\n\nProject text.\n\n<!-- agentic:begin -->\nOLD\n<!-- agentic:end -->\n\n## Mine\nkeep\n"


class Blocks(unittest.TestCase):
    def test_replace_keeps_project_part(self):
        self.assertEqual(il.replace_block(AGENTS, "NEW\n"), AGENTS.replace("OLD\n", "NEW\n"))

    def test_prose_mentioning_markers_is_not_a_marker(self):
        prose = "Do not edit between agentic:begin and agentic:end.\n"
        merged = il.replace_block(prose + AGENTS, "NEW\n")
        self.assertEqual(merged, prose + AGENTS.replace("OLD\n", "NEW\n"))

    def test_hash_marker_style(self):
        text = "# head\n# agentic:begin\n/Runtime/\n# agentic:end\n# mine\n"
        self.assertEqual(il.split_block(text)[1], "/Runtime/\n")

    def test_no_markers(self):
        self.assertIsNone(il.split_block("no markers here, only agentic:begin in prose\n"))


class Versions(unittest.TestCase):
    def test_dev_precedes_release(self):
        self.assertLess(il.parse_version("0.2.0-dev"), il.parse_version("0.2.0"))
        self.assertLess(il.parse_version("0.1.0"), il.parse_version("0.2.0-dev"))
        self.assertFalse(il.is_release("0.2.0-dev"))
        with self.assertRaises(il.InstallerError):
            il.parse_version("0.2.0-rc1")

    def test_fetch_ordering_matches(self):
        self.assertLess(update_cmd._version("0.1.0-dev"), (0, 1, 0, 1))  # tag v0.1.0
        self.assertEqual(update_cmd._version("0.1.0"), (0, 1, 0, 1))

    def test_migration_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / il.MIGRATIONS_DIR
            base.mkdir(parents=True)
            for name in ("0.2.0_a.py", "0.3.0_b.py"):
                (base / name).write_text("def migrate(root):\n    pass\n", encoding="utf-8")

            def names(old: str, new: str) -> list[str]:
                return [p.name for _v, p in il.list_migrations(Path(tmp), old, new)]

            self.assertEqual(names("0.1.0", "0.2.0"), ["0.2.0_a.py"])
            self.assertEqual(names("0.1.0", "0.2.0-dev"), ["0.2.0_a.py"])  # dev state carries it
            self.assertEqual(names("0.2.0-dev", "0.2.0"), ["0.2.0_a.py"])  # idempotent re-run
            self.assertEqual(names("0.2.0", "0.3.0"), ["0.3.0_b.py"])
            self.assertEqual(names("0.3.0", "0.3.0"), [])


class Classify(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def entry(self, text: str, cls: str = "managed") -> il.Entry:
        return il.Entry("f.md", text.encode(), cls, "core", False, "payload/f.md", True)

    def write(self, text: str) -> None:
        (self.root / "f.md").write_text(text, encoding="utf-8")

    def status(self, local: str | None, base: str | None, theirs: str | None, cls: str = "managed") -> str:
        if local is not None:
            self.write(local)
        else:
            (self.root / "f.md").unlink(missing_ok=True)
        lock = None if base is None else {"class": cls, "module": "core", "sha256": self.entry(base, cls).sha256}
        entry = None if theirs is None else self.entry(theirs, cls)
        return update.classify(self.root, "f.md", lock, entry).status

    def test_managed(self):
        self.assertEqual(self.status("a", "a", "a"), "unchanged")
        self.assertEqual(self.status("a", "a", "b"), "update")
        self.assertEqual(self.status("x", "a", "a"), "local-modified")
        self.assertEqual(self.status("x", "a", "b"), "conflict")
        self.assertEqual(self.status("b", "a", "b"), "already-current")
        self.assertEqual(self.status("a", "a", None), "remove")
        self.assertEqual(self.status("x", "a", None), "conflict")
        self.assertEqual(self.status(None, None, "a"), "add")

    def test_block_lost_markers(self):
        base = "head\n<!-- agentic:begin -->\nA\n<!-- agentic:end -->\n"
        self.write("head\nA\n")
        lock = {"class": "block", "module": "core", "sha256": self.entry(base, "block").sha256}
        item = update.classify(self.root, "f.md", lock, self.entry(base.replace("A\n", "B\n"), "block"))
        self.assertEqual((item.status, item.local), ("conflict", il.NO_MARKERS))

    def test_seeded_never_overwritten(self):
        self.assertEqual(self.status("mine", "a", "b", cls="seeded"), "seeded-changed")


class Secrets(unittest.TestCase):
    FOUND = [
        "password: hunter2hunter2",
        "DB_PASSWORD=S3cr3tPassw0rd",
        "Authorization: Bearer abcDEF1234567890ghijklmnop",
        "postgres://app:Prod1Passw0rd@db.internal:5432/app",
        "aws_secret_access_key = \"abcdEFGHijklMNOPqrstUVWXyz0123456789ABCD\"",
        "token = 'a1b2c3d4e5f6g7h8'",
        "пароль: Qwerty123456",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
        "-----" + "BEGIN RSA PRIVATE KEY-----",
        "AK" + "IA" + "ABCDEFGHIJKLMNOP",
    ]
    CLEAN = [
        "password: <your-password>",
        "postgres://user:password@localhost:5432/db",
        "postgres://user:${DB_PASS}@localhost/db",
        "token = os.environ['TOKEN']",
        "max_tokens=4096",
        "secret_name: my-app-secret",
        "token_file: /etc/app/token1.txt",
        "password: changeme123",
        "git@github.com:org/api.git",
        "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "password: hunter2hunter2  # agentic:allow-secret",
    ]

    def test_found(self):
        for text in self.FOUND:
            with self.subTest(text=text):
                self.assertTrue(secret_scan.scan_text(text), text)

    def test_clean(self):
        for text in self.CLEAN:
            with self.subTest(text=text):
                self.assertEqual(secret_scan.scan_text(text), [], text)


class ResourceUrls(unittest.TestCase):
    def test_local_paths(self):
        for url in ("/srv/repos/api", "./api", "../api", "~/src/api", "C:\\src\\api", "file:///srv/api"):
            self.assertTrue(resources.is_local_path(url), url)
        for url in ("git@github.com:org/api.git", "https://github.com/org/api.git", "ssh://git@host/x.git"):
            self.assertFalse(resources.is_local_path(url), url)


if __name__ == "__main__":
    os.environ.setdefault("AGENTIC_ROOT", str(TEMPLATE_ROOT))
    unittest.main(verbosity=1)
