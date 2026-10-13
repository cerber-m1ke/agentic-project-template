# /// script
# requires-python = ">=3.12"
# dependencies = ["tomli-w>=1", "pyyaml>=6", "snowballstemmer>=2.2"]
# [tool.uv]
# exclude-newer = "2026-10-01T00:00:00Z"
# ///
"""Unit tests of the parts where a mistake loses project data or misleads the user: managed-block
markers, versions and migrations, update classification, payload files, the secret scanner,
resource URLs, Knowledge note statuses, IDE excludes.

    TB_ROOT=. payload/modules/core/Toolbox/tb run setup/tests/unit_test.py
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import json  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402
from datetime import date  # noqa: E402
from pathlib import Path  # noqa: E402

TEMPLATE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(TEMPLATE_ROOT / "setup"))
sys.path.insert(0, str(TEMPLATE_ROOT / "payload" / "modules" / "core" / "Toolbox" / "agentic"))

import installer_lib as il  # noqa: E402
import update  # noqa: E402
import ide  # noqa: E402
import kb  # noqa: E402
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


class PayloadFiles(unittest.TestCase):
    """Only template files reach a project: never what git ignores in payload/ (editor and Obsidian
    folders, a Runtime/ made by tb started without TB_ROOT)."""

    JUNK = ("Runtime/tools/uv/uv", ".idea/workspace.xml", "Knowledge/.obsidian/app.json",
            "sub/__pycache__/x.pyc")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.core = self.root / il.MODULES_DIR / "core"
        files = {"module.toml": 'name = "core"\n', ".gitignore": "/Runtime/\n", "a.ru.md": "ru\n",
                 "a.en.md": "en\n", "sub/b.md": "b\n", **{j: "junk\n" for j in self.JUNK}}
        for rel, text in files.items():
            (self.core / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.core / rel).write_text(text, encoding="utf-8")
        (self.root / ".gitignore").write_text(".idea/\n.obsidian/\n__pycache__/\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def files(self) -> list[str]:
        module = il.load_modules(self.root)["core"]
        return [dest for dest, _src in il.module_files(module, "ru", self.root)]

    def git(self, *args: str) -> None:
        res = il.run(["git", "-c", "user.name=Unit", "-c", "user.email=unit@example.com",
                      "-c", "commit.gpgsign=false", *args], cwd=self.root)
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_unpacked_archive_skips_junk_folders(self):
        self.assertEqual(sorted(self.files()), [".gitignore", "a.md", "sub/b.md"])

    def test_git_clone_skips_ignored_and_deleted_files(self):
        self.git("init", "--quiet")
        (self.core / "gone.md").write_text("gone\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "--quiet", "-m", "init")
        (self.core / "gone.md").unlink()
        (self.core / "new.md").write_text("new\n", encoding="utf-8")  # untracked, not ignored
        self.assertEqual(sorted(self.files()), [".gitignore", "a.md", "new.md", "sub/b.md"])


class ResourceUrls(unittest.TestCase):
    def test_local_paths(self):
        for url in ("/srv/repos/api", "./api", "../api", "~/src/api", "C:\\src\\api", "file:///srv/api"):
            self.assertTrue(resources.is_local_path(url), url)
        for url in ("git@github.com:org/api.git", "https://github.com/org/api.git", "ssh://git@host/x.git"):
            self.assertFalse(resources.is_local_path(url), url)


class NoteStatuses(unittest.TestCase):
    def lint(self, folder: str, front: str) -> list[tuple[str, str]]:
        with tempfile.TemporaryDirectory() as tmp:
            kdir = Path(tmp) / "Knowledge"
            path = kdir / folder / "note.md"
            path.parent.mkdir(parents=True)
            path.write_text(f"---\n{front}title: T\ndescription: D\ncreated: 2026-01-01\n---\n\nBody\n",
                            encoding="utf-8")
            note = kb.parse_note(path, kdir)
            return [(p.level, p.message) for p in kb.lint_note(note, {}, None, date(2026, 10, 1))]

    def test_live_statuses(self):
        self.assertEqual(self.lint("Decisions", "type: decision\nstatus: accepted\n"), [])
        self.assertEqual(self.lint("Gotchas", "type: gotcha\n"), [])
        self.assertEqual(self.lint("Examples", "type: example\n"), [])

    def test_status_required_only_with_statuses(self):
        self.assertIn(("error", "missing required key 'status'"), self.lint("Plans", "type: plan\n"))

    def test_retired_and_extra_statuses_warn(self):
        for folder, front in (("Decisions", "type: decision\nstatus: superseded\nsuperseded_by: x.md\n"),
                              ("Gotchas", "type: gotcha\nstatus: resolved\n"),
                              ("Gotchas", "type: gotcha\nstatus: active\n"),
                              ("Plans", "type: plan\nstatus: dropped\n")):
            problems = self.lint(folder, front)
            self.assertTrue(problems, front)
            self.assertEqual({level for level, _ in problems}, {"warning"}, problems)

    def test_unknown_status_is_an_error(self):
        self.assertEqual(self.lint("Plans", "type: plan\nstatus: wip\n")[0][0], "error")

    def test_migration_drops_active_status(self):
        migration = TEMPLATE_ROOT / il.MIGRATIONS_DIR / "0.2.0_drop-status-gotcha-example.py"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = {
                "Knowledge/Gotchas/a.md": ("---\ntype: gotcha\nstatus: active\ntitle: A\n---\nstatus: active\n",
                                           "---\ntype: gotcha\ntitle: A\n---\nstatus: active\n"),
                "Knowledge/Gotchas/b.md": ("---\ntype: gotcha\nstatus: resolved\n---\n",) * 2,
                "Knowledge/Examples/c.md": ("---\ntype: example\nstatus: \"active\"\n---\n",
                                            "---\ntype: example\n---\n"),
                "Knowledge/Plans/d.md": ("---\ntype: plan\nstatus: active\n---\n",) * 2,
                "Knowledge/_templates/gotcha.md": ("---\ntype: gotcha\nstatus: active\n---\n",
                                                   "---\ntype: gotcha\n---\n"),
            }
            for rel, (before, _after) in files.items():
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text(before, encoding="utf-8")
            for _ in range(2):  # idempotent
                il.run_migration(migration, root)
                for rel, (_before, after) in files.items():
                    self.assertEqual((root / rel).read_text(encoding="utf-8"), after, rel)


class IdeExcludes(unittest.TestCase):
    IML = ('<?xml version="1.0" encoding="UTF-8"?>\n<module type="WEB_MODULE" version="4">\n'
           '  <component name="NewModuleRootManager">\n    {content}\n'
           '    <orderEntry type="sourceFolder" forTests="false" />\n  </component>\n</module>\n')
    MODULES = ('<?xml version="1.0" encoding="UTF-8"?>\n<project version="4">\n'
               '  <component name="ProjectModuleManager">\n    <modules>\n'
               '      <module fileurl="file://$PROJECT_DIR$/.idea/demo.iml" filepath="$PROJECT_DIR$/.idea/demo.iml" />\n'
               '    </modules>\n  </component>\n</project>\n')

    def excludes(self, iml: Path) -> list[str]:
        return [e.get("url") for e in ide.ET.parse(iml).iter("excludeFolder")]

    def test_new_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "My Project"
            root.mkdir()
            self.assertTrue(ide._jetbrains(root))
            iml = root / ".idea" / "My-Project.iml"
            self.assertEqual(self.excludes(iml), ["file://$MODULE_DIR$/Resources", "file://$MODULE_DIR$/Runtime"])
            self.assertEqual(ide._module_files(root), [iml])
            before = iml.read_text(encoding="utf-8")
            self.assertTrue(ide._jetbrains(root))
            self.assertEqual(iml.read_text(encoding="utf-8"), before)

    def run_iml(self, content: str) -> tuple[Path, str]:
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp))
        root = Path(tmp)
        (root / ".idea").mkdir()
        (root / ".idea" / "modules.xml").write_text(self.MODULES, encoding="utf-8")
        iml = root / ".idea" / "demo.iml"
        iml.write_text(self.IML.format(content=content), encoding="utf-8")
        self.assertTrue(ide._jetbrains(root))
        text = iml.read_text(encoding="utf-8")
        self.assertTrue(ide._jetbrains(root))
        self.assertEqual(iml.read_text(encoding="utf-8"), text, "second run changes nothing")
        return iml, text

    def test_self_closing_content(self):
        iml, text = self.run_iml('<content url="file://$MODULE_DIR$" />')
        self.assertEqual(self.excludes(iml), ["file://$MODULE_DIR$/Resources", "file://$MODULE_DIR$/Runtime"])
        self.assertIn('<orderEntry type="sourceFolder"', text)

    def test_adds_only_missing(self):
        iml, _ = self.run_iml('<content url="file://$MODULE_DIR$">\n'
                              '      <excludeFolder url="file://$MODULE_DIR$/Resources" />\n'
                              '      <excludeFolder url="file://$MODULE_DIR$/node_modules" />\n    </content>')
        self.assertEqual(sorted(self.excludes(iml)), ["file://$MODULE_DIR$/Resources", "file://$MODULE_DIR$/Runtime",
                                                      "file://$MODULE_DIR$/node_modules"])

    def test_vscode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = root / ".vscode" / "settings.json"
            settings.parent.mkdir()
            settings.write_text('{"editor.tabSize": 2, "search.exclude": {"dist/**": true}}', encoding="utf-8")
            self.assertTrue(ide._vscode(root))
            data = json.loads(settings.read_text(encoding="utf-8"))
            self.assertEqual(data["editor.tabSize"], 2)
            self.assertEqual(data["search.exclude"], {"dist/**": True, "Resources/**": True, "Runtime/**": True})
            self.assertEqual(data["files.watcherExclude"], {"Resources/**": True, "Runtime/**": True})
            jsonc = '{\n  // comment\n  "editor.tabSize": 2,\n}\n'
            settings.write_text(jsonc, encoding="utf-8")
            self.assertTrue(ide._vscode(root))
            self.assertEqual(settings.read_text(encoding="utf-8"), jsonc, "JSONC is left untouched")


if __name__ == "__main__":
    os.environ.setdefault("AGENTIC_ROOT", str(TEMPLATE_ROOT))
    unittest.main(verbosity=1)
