# /// script
# requires-python = ">=3.12"
# dependencies = ["tomli-w>=1", "pyyaml>=6", "snowballstemmer>=2.2"]
# [tool.uv]
# exclude-newer = "2026-10-01T00:00:00Z"
# ///
"""Unit tests of the parts where a mistake loses project data or misleads the user: managed-block
markers, versions and migrations, update classification, payload files, the secret scanner,
resource URLs, Knowledge note statuses, IDE excludes, adopt ledgers, links and archives.

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
sys.path.insert(0, str(TEMPLATE_ROOT / "payload" / "modules" / "adopt" / "Toolbox" / "agentic"))

import adopt  # noqa: E402
import adopt_sources  # noqa: E402
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


class KnowledgeProject(unittest.TestCase):
    """A temporary project root for `tb kb` (common.project_root() is redirected to it)."""

    STATUS = {"Decisions": "accepted", "Entities": "active", "Plans": "idea", "Tasks": "active"}

    def setUp(self):
        import common

        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        saved = common._root
        common._root = self.root

        def restore():
            common._root = saved
            kb._snapshot = None
            self.tmp.cleanup()

        self.addCleanup(restore)

    def write(self, rel: str, text: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        return path

    def note(self, rel: str, body: str = "Body\n", front: str = "") -> Path:
        folder = rel.split("/")[0]
        status = f"status: {self.STATUS[folder]}\n" if folder in self.STATUS else ""
        return self.write(f"Knowledge/{rel}", f"---\ntype: {kb.common.FOLDER_TO_TYPE[folder]}\n{status}"
                                              f"title: T\ndescription: D\ncreated: 2026-01-01\n{front}---\n\n{body}")

    def lint(self, staged: bool = False) -> list[tuple[str, str, str]]:
        problems, _count = kb.run_lint(staged=staged)
        self.assertIsNone(kb._snapshot)
        return [(p.path, p.level, p.message) for p in problems]

    def git(self, *args: str) -> None:
        res = il.run(["git", "-c", "user.name=Unit", "-c", "user.email=unit@example.com", *args], cwd=self.root)
        self.assertEqual(res.returncode, 0, res.stderr)

    def tb(self, func, **kwargs) -> tuple[int, str]:
        import argparse
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = func(argparse.Namespace(**kwargs))
        return code, buf.getvalue()


class KbPendingLinks(KnowledgeProject):
    A = "Knowledge/Gotchas/a.md"

    def test_pending_link_is_a_warning_until_the_target_exists(self):
        self.note("Gotchas/a.md", '[B](b.md "pending"), [C](c.md \'pending\'), [D](d.md (pending)), '
                                  '[E](e.md "Title")\n')
        problems = self.lint()
        self.assertIn((self.A, "warning", "pending link: b.md"), problems)
        self.assertIn((self.A, "warning", "pending link: c.md"), problems)
        self.assertIn((self.A, "warning", "pending link: d.md"), problems)
        self.assertIn((self.A, "error", "broken link: e.md"), problems)
        self.note("Gotchas/b.md")
        self.assertIn((self.A, "warning", 'pending link target now exists: remove the "pending" title (b.md)'),
                      self.lint())

    def test_stale_and_related_show_pending_links(self):
        self.note("Gotchas/a.md", '[B](b.md "pending") [C](c.md "pending")\n')
        self.note("Gotchas/c.md")
        note = next(n for n in kb.load_notes() if n.slug == "a")
        reason = kb.pending_reason(note)
        self.assertIn("1 pending link (write the target", reason)
        self.assertIn('1 pending link with an existing target (remove the "pending" title)', reason)
        code, out = self.tb(kb.cmd_stale, days=None)
        self.assertEqual(code, 0)
        self.assertIn(f"{self.A}  [gotcha]  ", out)
        code, out = self.tb(kb.cmd_related, ref="a")
        self.assertIn("Knowledge/Gotchas/b.md  [pending]", out)
        self.assertIn("Knowledge/Gotchas/c.md — T  [pending]", out)

    def test_staged_link_to_an_unstaged_note_is_a_warning(self):
        self.git("init", "--quiet")
        self.note("Gotchas/a.md", "[B](b.md) [C](c.md)\n")
        self.note("Gotchas/b.md")  # on disk, committed later by another session
        self.git("add", "--", self.A)
        problems = [p for p in self.lint(staged=True) if p[0] == self.A]
        self.assertEqual(problems, [
            (self.A, "warning", "link target is not staged yet (commit it together or later): b.md"),
            (self.A, "error", "broken link: c.md")])
        self.git("add", "--", "Knowledge/Gotchas/b.md")
        self.assertEqual([p for p in self.lint(staged=True) if p[0] == self.A],
                         [(self.A, "error", "broken link: c.md")])

    def test_staged_link_to_an_ignored_file_is_an_error(self):
        self.git("init", "--quiet")
        self.write(".gitignore", "/Runtime/\n")
        self.write("Runtime/out.md", "x\n")
        self.write("Knowledge/Gotchas/draft.md", "x\n")
        self.note("Gotchas/a.md", "[R](../../Runtime/out.md) [D](draft.md)\n")
        self.write("Resources/resources.toml", '[[resource]]\nname = "api"\nkind = "git"\nurl = "x"\n'
                                               'entity = "Runtime/out.md"\n')
        self.git("add", "--", self.A, ".gitignore", "Resources/resources.toml")
        problems = self.lint(staged=True)
        self.assertEqual([p for p in problems if p[0] == self.A], [
            (self.A, "error", "broken link: ../../Runtime/out.md (ignored by git, never committed)"),
            (self.A, "warning", "link target is not staged yet (commit it together or later): draft.md")])
        self.assertIn(("Resources/resources.toml", "error",
                       "resource 'api': entity is ignored by git (never committed): Runtime/out.md"), problems)


class KbResources(KnowledgeProject):
    CATALOG = ('[[resource]]\nname = "api"\nkind = "git"\nurl = "x"\nentity = "Knowledge/Entities/api.md"\n\n'
               '[[resource]]\nname = "web"\nkind = "git"\nurl = "y"\n')

    def test_resource_ref(self):
        self.assertEqual(kb.resource_ref("api"), ("api", ""))
        self.assertEqual(kb.resource_ref("api@feature/x"), ("api", ""))
        self.assertEqual(kb.resource_ref("api/src/billing/@feature/x"), ("api", "src/billing"))
        self.assertEqual(kb.resource_ref({"name": "api/docs", "branch": "main"}), ("api", "docs"))
        self.assertIsNone(kb.resource_ref("  "))
        self.assertEqual(kb.resource_name("api/docs@main"), "api")

    def test_search_by_resource_and_subpath(self):
        for slug, res in (("whole", "api"), ("billing", "api/src/billing"), ("deep", "api/src/billing/tax"),
                          ("docs", "api/docs@main"), ("web", "web")):
            self.note(f"Gotchas/{slug}.md", front=f"resources: [{res}]\n")
        notes = kb.load_notes()

        def found(resource: str) -> list[str]:
            return sorted(h.note.slug for h in kb.run_search("", notes, resource=resource))

        self.assertEqual(found("api"), ["billing", "deep", "docs", "whole"])
        self.assertEqual(found("api/src"), ["billing", "deep"])
        self.assertEqual(found("api/src/billing"), ["billing", "deep"])
        self.assertEqual(found("api/src/bill"), [])
        self.assertEqual(found("web/x"), [])

    def test_lint_subpath_and_entity(self):
        self.write("Resources/resources.toml", self.CATALOG)
        (self.root / "Resources" / "api" / "src").mkdir(parents=True)
        self.note("Gotchas/a.md", front="resources: [api/src, api/gone@main, web/not-cloned, zzz/x]\n")
        self.note("Entities/web-card.md", front="resources: [web]\n")
        self.note("Entities/api-docs.md", front="resources: [web/docs]\n")
        a, card = "Knowledge/Gotchas/a.md", "Knowledge/Entities/web-card.md"
        problems = self.lint()
        self.assertIn(("Resources/resources.toml", "error",
                       "resource 'api': entity file not found: Knowledge/Entities/api.md"), problems)
        self.assertIn((a, "warning", "resource path not found: api/gone (no Resources/api/gone in the clone)"),
                      problems)
        self.assertIn((a, "error", "unknown resource 'zzz' (not in Resources/resources.toml)"), problems)
        self.assertIn((card, "warning", "resource 'web' has no 'entity'; set it: "
                                        f"Toolbox/tb resources set web entity={card}"), problems)
        mine = [p for p in problems if p[0] in (a, card, "Knowledge/Entities/api-docs.md",
                                                "Resources/resources.toml")]
        self.assertEqual(len(mine), 4, mine)
        self.assertEqual(kb.check_catalog_entities(kb.load_catalog([]), self.CATALOG)[0].line, 5)
        self.note("Entities/api.md")
        self.assertFalse([p for p in self.lint() if p[0] == "Resources/resources.toml"])

    def test_entity_hint_only_for_the_resource_card(self):
        self.write("Resources/resources.toml", self.CATALOG)
        self.note("Entities/api.md")
        self.note("Entities/frontend.md", front="resources: [web]\n")
        self.note("Entities/web-cdn.md", front="resources: [web, web/cdn]\n")
        hints = [p for p in self.lint() if "has no 'entity'" in p[2]]
        self.assertEqual(hints, [], "two cards list 'web', none is named after it")
        self.note("Entities/web.md", front="resources: [web]\n")
        hints = [p[0] for p in self.lint() if "has no 'entity'" in p[2]]
        self.assertEqual(hints, ["Knowledge/Entities/web.md"])

    def test_entity_hint_skips_a_card_of_another_resource(self):
        self.write("Resources/resources.toml", self.CATALOG)
        self.note("Entities/api.md", front="resources: [api, web]\n")  # the only card listing web
        self.assertEqual([p for p in self.lint() if "has no 'entity'" in p[2]], [],
                         "api.md is already the entity of 'api'")

    def test_staged_catalog_entity(self):
        self.git("init", "--quiet")
        self.write("Resources/resources.toml", self.CATALOG)
        self.note("Entities/api.md")
        self.git("add", "--", "Resources/resources.toml")
        self.assertIn(("Resources/resources.toml", "warning", "resource 'api': entity is not staged yet "
                       "(commit it together or later): Knowledge/Entities/api.md"), self.lint(staged=True))
        (self.root / "Knowledge" / "Entities" / "api.md").unlink()
        self.assertIn(("Resources/resources.toml", "error",
                       "resource 'api': entity file not found: Knowledge/Entities/api.md"), self.lint(staged=True))


class KbVerify(KnowledgeProject):
    def test_set_verified_keeps_other_bytes(self):
        crlf = "\ufeff---\r\ntype: gotcha\r\ncreated: 2026-01-01\r\nverified: 2026-02-01   # checked\r\n---\r\nBody\r\n"
        self.assertEqual(kb.set_verified(crlf, "2026-10-22"), crlf.replace("2026-02-01", "2026-10-22"))
        text = "---\ntype: x\ncreated: 2026-01-01  # c\ntags: [a,  b]\n---\n\nverified: in body\n"
        self.assertEqual(kb.set_verified(text, "2026-10-22"),
                         text.replace("# c\n", "# c\nverified: 2026-10-22\n"))
        self.assertEqual(kb.set_verified("---\ntype: x\n---\nb\n", "2026-10-22"),
                         "---\ntype: x\nverified: 2026-10-22\n---\nb\n")
        self.assertEqual(kb.set_verified("---\nverified:\n---\n", "2026-10-22"), "---\nverified: 2026-10-22\n---\n")
        self.assertIsNone(kb.set_verified("no frontmatter\n", "2026-10-22"))

    def test_set_verified_multiline_values(self):
        day = "2026-10-22"
        listed = "---\ntype: x\nverified:\n  - 2026-01-01\n  - 2026-02-01\n# tail\ntags: [a]\n---\nb\n"
        self.assertEqual(kb.set_verified(listed, day),
                         "---\ntype: x\nverified: 2026-10-22\n# tail\ntags: [a]\n---\nb\n")
        folded = "---\ntype: x\ncreated: >\n  2026-01-01\ntags: [a]\n---\nb\n"
        self.assertEqual(kb.set_verified(folded, day), folded.replace("01\n", "01\nverified: 2026-10-22\n"))
        literal = "---\ncreated: |\n  one\n  two\n---\nb\n"
        self.assertEqual(kb.set_verified(literal, day), literal.replace("two\n", "two\nverified: 2026-10-22\n"))
        quoted = '---\n"verified": 2026-01-01  # c\ntype: x\n---\nb\n'
        self.assertEqual(kb.set_verified(quoted, day), "---\nverified: 2026-10-22  # c\ntype: x\n---\nb\n")
        for unsafe in ("---\n{type: x}\n---\nb\n", "---\ntype: [x\n---\nb\n",
                       "---\nverified: 2026-01-01\nverified: 2026-02-01\n---\nb\n"):
            with self.subTest(unsafe=unsafe), self.assertRaises(ValueError):
                kb.set_verified(unsafe, day)

    def test_verify_refuses_an_unsafe_edit(self):
        path = self.write("Knowledge/Gotchas/flow.md", "---\n{type: gotcha, title: T, description: D, "
                                                       "created: 2026-01-01}\n---\nBody\n")
        before = path.read_bytes()
        code, out = self.tb(kb.cmd_verify, refs=["flow"], date="2026-03-01", dry_run=False)
        self.assertEqual((code, path.read_bytes()), (1, before))
        self.assertIn("cannot update 'verified' safely in Knowledge/Gotchas/flow.md; edit it by hand", out)

    def test_verify_dedups_slug_and_path(self):
        good = self.note("Gotchas/good.md")
        code, out = self.tb(kb.cmd_verify, refs=["good", "Knowledge/Gotchas/good.md", str(good)],
                            date="2026-03-01", dry_run=False)
        self.assertEqual(code, 0, out)
        self.assertEqual(out.count("set verified"), 1, out)
        self.assertIn("0 errors, 0 warnings (1 note checked)", out)

    def test_verify_command(self):
        good = self.note("Gotchas/good.md", front="tags: [x]   # keep\n")
        bad = self.note("Gotchas/bad.md", "[X](missing.md)\n", front="verified: 2026-02-01\n")
        before = good.read_bytes()
        code, out = self.tb(kb.cmd_verify, refs=["good", "Knowledge/Gotchas/bad.md"], date="2026-03-01", dry_run=True)
        self.assertEqual(good.read_bytes(), before)
        self.assertIn("would set verified: 2026-03-01", out)
        code, out = self.tb(kb.cmd_verify, refs=["good", "nope", "Knowledge/Gotchas/bad.md"], date="2026-03-01",
                            dry_run=False)
        self.assertEqual(code, 1)
        self.assertIn("note not found: nope", out)
        self.assertIn("Knowledge/Gotchas/bad.md:9: error: broken link: missing.md", out)
        self.assertEqual(good.read_bytes(), before.replace(b"2026-01-01\n", b"2026-01-01\nverified: 2026-03-01\n"))
        self.assertIn(b"\nverified: 2026-03-01\n", bad.read_bytes())
        code, out = self.tb(kb.cmd_verify, refs=["good"], date="2026-03-01", dry_run=False)
        self.assertEqual((code, good.read_bytes().count(b"verified:")), (0, 1))
        self.assertEqual(self.tb(kb.cmd_verify, refs=["good"], date="03/01/2026", dry_run=False)[0], 2)


class AgentsBudget(unittest.TestCase):
    def test_lint_counts_only_the_project_part(self):
        big, small = "word " * 1000, "word " * 100  # ~1250 and ~125 tokens
        block = "<!-- agentic:begin -->\n{}\n<!-- agentic:end -->\n"
        self.assertIsNone(kb.agents_budget_problem("# P\n" + small + "\n" + block.format(big)))
        problem = kb.agents_budget_problem("# P\n" + big + "\n" + block.format(small))
        self.assertIsNotNone(problem)
        self.assertIn("project part (outside the agentic block) ~1251 tokens, above the 800-token budget",
                      problem.message)
        self.assertIsNone(kb.agents_budget_problem(big))  # no markers: the whole file, 1500 tokens
        self.assertIsNotNone(kb.agents_budget_problem(big + big))

    def test_template_block_fits_its_budget(self):
        for lang in il.LANGS if hasattr(il, "LANGS") else ("ru", "en"):
            text = (TEMPLATE_ROOT / il.MODULES_DIR / "core" / f"AGENTS.{lang}.md").read_text(encoding="utf-8")
            sizes = {}
            for profile in il.list_profiles(TEMPLATE_ROOT):
                ctx = il.Context("demo-project", lang, profile, "2026-01-01", TEMPLATE_ROOT)
                sizes[profile] = kb.estimate_tokens(il.split_block(il.render(text, ctx, f"AGENTS.{lang}.md"))[1])
            with self.subTest(lang=lang):
                self.assertLessEqual(max(sizes.values()), kb.AGENTS_BLOCK_BUDGET, sizes)


class _ToolboxProject(unittest.TestCase):
    """A temporary project root for tb resources/agents; tb output is captured."""

    def setUp(self):
        import contextlib
        import io
        import common

        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        saved = common._root
        common._root = self.root
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(setattr, common, "_root", saved)
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        for redirect in (contextlib.redirect_stdout(self.stdout), contextlib.redirect_stderr(self.stderr)):
            redirect.__enter__()
            self.addCleanup(redirect.__exit__, None, None, None)

    def write(self, rel: str, text: str = "") -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        return path


class ResourcesSet(_ToolboxProject):
    CATALOG = ('# Catalog head\n\n'
               '[[resource]]\n'
               'name = "api"   # the key\n'
               'kind = "git"\n'
               'url = "git@example.com:org/api.git"\n'
               'description = "API"  # keep me\n'
               '# a comment before the next resource\n\n'
               '[[resource]]\n'
               'name = "lib"\n'
               'url = "https://example.com/lib.git#frag"\n'
               'agent_settings_reviewed = [\n'
               '    ".mcp.json",\n'
               ']\n')

    def setUp(self):
        super().setUp()
        self.path = self.write(resources.CATALOG, self.CATALOG)

    def text(self) -> str:
        return self.path.read_text(encoding="utf-8")

    def test_set_keeps_the_rest(self):
        self.assertEqual(resources.set_fields("api", ["description=Backend API", "branch=main"]), 0)
        self.assertEqual(self.text(), self.CATALOG.replace(
            'description = "API"  # keep me\n',
            'description = "Backend API"  # keep me\nbranch = "main"\n'))

    def test_empty_value_removes_field(self):
        self.assertEqual(resources.set_fields("api", ["description="]), 0)
        self.assertEqual(self.text(), self.CATALOG.replace('description = "API"  # keep me\n', ""))
        self.assertEqual(resources.set_fields("api", ["branch="]), 0, "removing an absent field is fine")
        self.assertIn("nothing to change", self.stdout.getvalue())

    def test_multiline_list_and_entity(self):
        self.assertEqual(resources.set_fields("lib", ["agent_settings_reviewed=.mcp.json, .codex/config.toml/",
                                                      "entity=Knowledge/Entities/lib.md"]), 0)
        self.assertTrue(self.text().endswith('url = "https://example.com/lib.git#frag"\n'
                                             'agent_settings_reviewed = [".mcp.json", ".codex/config.toml"]\n'
                                             'entity = "Knowledge/Entities/lib.md"\n'), self.text())
        self.assertIn("does not exist", self.stderr.getvalue())

    def test_validation_leaves_file_unchanged(self):
        for args in (["name=x"], ["owner=me"], ["kind=svn"], ["description"], ["url=a", "url=b"]):
            self.assertEqual(resources.set_fields("api", args), 1, args)
        self.assertEqual(resources.set_fields("nope", ["branch=main"]), 1)
        self.assertEqual(self.text(), self.CATALOG)

    def test_invalid_result_is_rolled_back(self):
        from unittest import mock
        with mock.patch.object(resources, "_toml_kv", return_value='branch = "x" = 1'):
            self.assertEqual(resources.set_fields("api", ["branch=main"]), 1)
        self.assertEqual(self.text(), self.CATALOG)
        self.assertIn("left unchanged", self.stderr.getvalue())

    def test_add_entity(self):
        self.write("Knowledge/Entities/web.md", "card\n")
        self.assertEqual(resources.add("https://example.com/org/web.git", description="Web",
                                       entity="Knowledge/Entities/web.md"), 0)
        self.assertTrue(self.text().endswith('[[resource]]\nname = "web"\nkind = "git"\n'
                                             'url = "https://example.com/org/web.git"\ndescription = "Web"\n'
                                             'entity = "Knowledge/Entities/web.md"\n'), self.text())
        self.assertNotIn("does not exist", self.stderr.getvalue())


class ResourcesReviewedSettings(_ToolboxProject):
    def test_only_unreviewed_are_reported(self):
        for rel in ("Resources/api/.mcp.json", "Resources/api/.claude/settings.json", "Resources/doc/.mcp.json",
                    "Resources/raw/.codex/config.toml"):
            self.write(rel, "{}\n")
        entries = [{"name": "api", "agent_settings_reviewed": [".mcp.json"]},
                   {"name": "doc", "agent_settings_reviewed": [".mcp.json/"]}]
        found = resources.unreviewed_agent_configs(entries)
        self.assertEqual([(name, new) for name, new, _ in found],
                         [("api", [".claude/settings.json"]), ("raw", [".codex/config.toml"])])
        self.assertEqual(found[0][2], "Toolbox/tb resources set api "
                                      "agent_settings_reviewed=.mcp.json,.claude/settings.json")
        self.assertEqual(found[1][2], "", "a folder outside the catalog gets no set hint")
        entries[0]["agent_settings_reviewed"].append(".claude/settings.json")
        self.assertEqual([n for n, _, _ in resources.unreviewed_agent_configs(entries)], ["raw"])


class PermissionRules(_ToolboxProject):
    RULES = ('[[command]]\nprefix = ["git", "push", "--force"]\ndecision = "deny"\n'
             'reason = "Rewrites \\"shared\\" history"\n\n'
             '[[command]]\nprefix = ["Toolbox/tb", "version"]\ndecision = "allow"\n\n'
             '[[command]]\nprefix = ["rm", "-rf", "~"]\ndecision = "ask"\n\n'
             '[claude]\ndeny = ["Read(./secrets/**)"]\n')

    def manifest(self, agent: str) -> dict:
        return resources.common.load_toml(
            TEMPLATE_ROOT / "payload/modules/core/.agents/adapters" / agent / "adapter.toml")

    def render(self, agent: str) -> tuple[dict[str, str], list[str]]:
        import adapters
        ctx = adapters.load_context(self.root, agent, self.manifest(agent))
        return adapters.render(ctx), ctx.source_warnings + ctx.warnings

    def test_claude_merges_with_template_allow(self):
        template = self.manifest("claude")["permissions"]["allow"]
        files, _ = self.render("claude")
        self.assertEqual(json.loads(files[".claude/settings.json"])["permissions"], {"allow": template})
        self.write(".agents/permissions.toml", self.RULES)
        files, warnings = self.render("claude")
        rules = json.loads(files[".claude/settings.json"])["permissions"]
        self.assertEqual(rules["deny"], ["Bash(git push --force)", "Bash(git push --force *)", "Read(./secrets/**)"])
        self.assertEqual(rules["ask"], ["Bash(rm -rf ~)", "Bash(rm -rf ~ *)"], "no shell quoting")
        self.assertEqual(rules["allow"], template + ["Bash(Toolbox/tb version *)"], "no duplicates")
        self.assertEqual(warnings, [])

    def test_codex_starlark_skips_claude_section(self):
        files, _ = self.render("codex")
        self.assertNotIn(".codex/rules/project.rules", files)
        self.write(".agents/permissions.toml", self.RULES)
        files, warnings = self.render("codex")
        rules = files[".codex/rules/project.rules"]
        self.assertIn('prefix_rule(\n    pattern = ["git", "push", "--force"],\n    decision = "forbidden",\n'
                      '    justification = "Rewrites \\"shared\\" history",\n)', rules)
        self.assertIn('pattern = ["rm", "-rf", "~"],\n    decision = "prompt",\n)', rules)
        self.assertIn('decision = "allow"', rules)
        self.assertTrue(rules.startswith("# generated by Toolbox/tb agents link"))
        self.assertEqual(warnings, [], "skipped [claude] rules are a note, not a warning")

    def test_invalid_rules_warn_and_are_skipped(self):
        self.write(".agents/permissions.toml",
                   '[[command]]\nprefix = []\ndecision = "deny"\n\n'
                   '[[command]]\nprefix = "git"\ndecision = "deny"\n\n'
                   '[[command]]\nprefix = ["rm", "-rf"]\ndecision = "block"\n\n'
                   '[[command]]\nprefix = ["rm"]\ndecision = "ask"\nreasn = "typo"\n\n'
                   '[claude]\ndeny = "Read(x)"\n\n[commands]\n')
        files, warnings = self.render("codex")
        self.assertEqual(files[".codex/rules/project.rules"].count("prefix_rule("), 1)
        self.assertEqual(len(warnings), 6, warnings)
        self.write(".agents/permissions.toml",
                   '[[command]]\nprefix = ["make", "deploy prod"]\ndecision = "ask"\n\n'
                   '[[command]]\nprefix = ["rm", "*.log"]\ndecision = "ask"\n\n'
                   '[[command]]\nprefix = ["echo", "\'x\'"]\ndecision = "ask"\n\n'
                   '[[command]]\nprefix = ["git", "push"]\ndecision = "ask"\n')
        for agent in ("claude", "codex"):
            files, warnings = self.render(agent)
            with self.subTest(agent=agent):
                self.assertEqual(len([w for w in warnings if "whitespace, quotes or `*`" in w]), 3, warnings)
        self.assertEqual(files[".codex/rules/project.rules"].count("prefix_rule("), 1)
        files, _ = self.render("claude")
        self.assertEqual(json.loads(files[".claude/settings.json"])["permissions"]["ask"],
                         ["Bash(git push)", "Bash(git push *)"])

    def link_both(self) -> int:
        import agents
        for agent in ("claude", "codex"):
            self.write(f".agents/adapters/{agent}/adapter.toml",
                       (TEMPLATE_ROOT / "payload/modules/core/.agents/adapters" / agent / "adapter.toml")
                       .read_text(encoding="utf-8"))
        return agents.link(["claude", "codex"])

    def test_unreadable_file_keeps_generated_rules(self):
        import agents
        self.write(".agents/permissions.toml", '[[command]]\nprefix = ["git", "push"]\ndecision = "deny"\n\n'
                                               '[claude]\ndeny = ["Read(./.env)"]\n')
        self.assertEqual(self.link_both(), 0, self.stdout.getvalue() + self.stderr.getvalue())
        settings, rules = self.root / ".claude/settings.json", self.root / ".codex/rules/project.rules"
        before = settings.read_bytes(), rules.read_bytes()
        self.assertIn(b"Bash(git push)", before[0])
        self.assertIn("note: .agents/permissions.toml: [claude] has 1", self.stdout.getvalue())
        for broken in ("oops = [\n", "command = 1\n"):
            self.write(".agents/permissions.toml", broken)
            with self.subTest(broken=broken):
                self.assertEqual(self.link_both(), 1)
                self.assertEqual((settings.read_bytes(), rules.read_bytes()), before)
                self.assertIn(".claude/settings.json: not updated — .agents/permissions.toml:", self.stdout.getvalue())
                self.assertIn(".codex/rules/project.rules: not updated", self.stdout.getvalue())
                mark = len(self.stdout.getvalue())
                self.assertEqual(agents.cmd_doctor(None), 1)
                self.assertIn("✗ .codex/rules/project.rules: kept as is — .agents/permissions.toml:",
                              self.stdout.getvalue()[mark:])

    def test_shared_warnings_once_and_notes_are_not_warnings(self):
        import agents
        self.write(".agents/permissions.toml", '[[command]]\nprefix = []\ndecision = "deny"\n\n'
                                               '[claude]\ndeny = ["Read(./.env)"]\n')
        self.assertEqual(self.link_both(), 0)
        self.assertEqual(self.stderr.getvalue().count("command #1"), 1, self.stderr.getvalue())
        mark = len(self.stdout.getvalue())
        agents.cmd_doctor(None)
        doctor = self.stdout.getvalue()[mark:]
        self.assertEqual(doctor.count("command #1"), 1, doctor)
        self.assertIn("· .agents/permissions.toml: [claude] has 1", doctor)
        self.assertNotIn("! .agents/permissions.toml: [claude]", doctor)


class AdoptProject(KnowledgeProject):
    """A temporary project with the adopt templates installed (ru) and a fake HOME with old places."""

    ADOPT = TEMPLATE_ROOT / "payload" / "modules" / "adopt"

    def setUp(self):
        super().setUp()
        self.home = self.root.parent / (self.root.name + "-home")
        self.home.mkdir()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.home, ignore_errors=True))
        saved = {k: os.environ.get(k) for k in ("HOME", "USERPROFILE")}
        os.environ["HOME"] = os.environ["USERPROFILE"] = str(self.home)

        def restore():
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

        self.addCleanup(restore)
        module = il.load_modules(TEMPLATE_ROOT)["adopt"]
        for dest, src in il.module_files(module, "ru", TEMPLATE_ROOT):
            if dest.startswith(adopt.TEMPLATES):
                self.write(dest, (TEMPLATE_ROOT / src).read_text(encoding="utf-8"))

    def run_cmd(self, func, **kwargs) -> tuple[int, str]:
        kwargs.setdefault("task", None)
        return self.tb(func, **kwargs)

    def start(self, *old: Path) -> adopt.Task:
        code, out = self.tb(adopt.cmd_start, slug="move", title=None, old_root=[str(p) for p in old],
                            archive_dir=str(self.home / "Archive"))
        self.assertEqual(code, 0, out)
        return adopt.find_task(None)

    def add_sources(self, text: str) -> adopt.Task:
        cfg = self.root / adopt.TASKS_DIR / "move" / adopt.CONFIG
        cfg.write_text(cfg.read_text(encoding="utf-8") + "\n" + text, encoding="utf-8")
        return adopt.find_task(None)

    def batch(self, source: str, name: str, rows: list[str], extra: str = "") -> Path:
        table = ["# x", "", "| Источник | Вердикт | Цель | Причина | Аудит |", "|---|---|---|---|---|", *rows]
        return self.write(f"{adopt.TASKS_DIR}/move/ledger/{source}/{name}.md", "\n".join(table) + "\n" + extra)


class AdoptBasics(unittest.TestCase):
    def test_to_slug(self):
        cases = {"2026-03-01-Кэш_токенов": "kesh-tokenov", "Auth Tokens (v2)": "auth-tokens-v2", "CON": "con-note",
                 "2026-01-01": "2026-01-01", "": "note", "Щука ёлка": "shchuka-elka"}
        for stem, slug in cases.items():
            with self.subTest(stem=stem):
                self.assertEqual(adopt.to_slug(stem), slug)

    def test_cells_and_targets(self):
        self.assertEqual(adopt.split_cells("| a \\| b | `c` | d |"), ["a | b", "c", "d"])
        self.assertEqual(adopt.split_targets("`Knowledge/A/x.md`<br>Knowledge/B/y.md, —"),
                         ["Knowledge/A/x.md", "Knowledge/B/y.md"])

    def test_claude_dir_name(self):
        self.assertEqual(adopt_sources.claude_dir_name(Path("/Users/me/src/my_api.v2")), "-Users-me-src-my-api-v2")

    def test_digest_redacts_secrets(self):
        secret = "DB_PASSWORD=S3cr3tPassw0rd"  # agentic:allow-secret (test fixture)
        text = adopt_sources.redact(f"run with {secret} please")
        self.assertNotIn("S3cr3tPassw0rd", text)
        self.assertIn("[secret:", text)
        pem = "-----" + "BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA1234\n-----" + "END RSA PRIVATE KEY-----"
        self.assertEqual(adopt_sources.redact(f"key:\n{pem}\ndone"), "key:\n[secret: private key]\ndone")


class AdoptStart(AdoptProject):
    def test_start_creates_a_lint_clean_task(self):
        task = self.start(self.home / "appOld")
        self.assertEqual(task.old_roots, ["~/appOld"])
        self.assertEqual(task.archive_dir, "~/Archive")
        for name in ("index.md", "plan.md", "rules.md", "resources.md", "questions.md", "final-audit.md",
                     "deletion-manifest.md", "ledger/README.md", "adopt.toml"):
            self.assertTrue((task.dir / name).is_file(), name)
        index = (task.dir / "index.md").read_text(encoding="utf-8")
        self.assertIn('title: "Adopt: move"', index)
        self.assertIn("--task move", index)
        self.assertNotIn("{{", index + (task.dir / "plan.md").read_text(encoding="utf-8"))
        self.assertEqual([p for p in self.lint() if p[1] == "error"], [])
        code, out = self.tb(adopt.cmd_start, slug="move", title=None, old_root=[], archive_dir=None)
        self.assertEqual(code, 1)
        self.assertIn("already exists", out)

    def test_no_task(self):
        with self.assertRaises(adopt.AdoptError):
            adopt.find_task(None)


class AdoptLedger(AdoptProject):
    def setUp(self):
        super().setUp()
        vault = self.home / "Vaults" / "App"
        for name in ("2026-01-02-auth.md", "cache.md", "gone.md"):
            p = vault / "decisions" / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"# {name}\n\nSee [[cache]] and [[gone|the old one]].\n", encoding="utf-8")
        self.start(self.home / "appOld")
        self.task = self.add_sources('[[source]]\nname = "vault-decisions"\nkind = "vault"\n'
                                     'paths = ["~/Vaults/App/decisions"]\nfolder = "Decisions"\n\n'
                                     '[[source]]\nname = "memory"\nkind = "claude-memory"\npaths = ["~/nowhere"]\n')
        code, out = self.run_cmd(adopt.cmd_manifest, source=None)
        self.assertEqual(code, 0, out)
        self.entries = adopt.read_manifest(self.task, "vault-decisions")
        self.auth, self.cache, self.gone = self.entries

    def check(self, source: str = "vault-decisions", batch: str | None = None, pre: bool = False):
        return self.run_cmd(adopt.cmd_check, source=source, batch=batch, pre_audit=pre)

    def test_manifest_uses_tilde_paths(self):
        self.assertEqual(self.entries, ["~/Vaults/App/decisions/2026-01-02-auth.md",
                                        "~/Vaults/App/decisions/cache.md", "~/Vaults/App/decisions/gone.md"])
        self.assertEqual(adopt.read_manifest(self.task, "memory"), [])

    def test_check_errors(self):
        self.note("Decisions/auth.md")
        self.batch("vault-decisions", "01", [
            f"| {self.auth} | migrated | Knowledge/Decisions/auth.md | | ok |",
            f"| {self.auth} | obsolete | | done | ok |",
            f"| {self.cache} | migrated | Knowledge/Decisions/missing.md | | fix: wrong |",
            "| ~/elsewhere.md | junk | | | |",
            "| only | three | cells |",
        ])
        code, out = self.check()
        self.assertEqual(code, 1, out)
        for msg in ("covered 2 times", "target does not exist", "audit is 'fix: wrong'", "not in the manifest",
                    "verdict junk needs a reason", "expected 5 columns", f"{self.gone}: not covered", "RED"):
            self.assertIn(msg, out)

    def test_pre_audit_then_green(self):
        self.note("Decisions/auth.md")
        self.note("Decisions/cache.md")
        rows = [f"| {self.auth} | migrated | Knowledge/Decisions/auth.md | | |",
                f"| {self.cache} | duplicate-candidate | Knowledge/Decisions/auth.md | same topic | |",
                f"| {self.gone} | obsolete | | removed in a1b2c3d | |"]
        self.batch("vault-decisions", "01", rows)
        code, out = self.check(batch="01", pre=True)
        self.assertEqual(code, 0, out)
        code, out = self.check()
        self.assertIn("duplicate-candidate is not resolved", out)
        self.batch("vault-decisions", "01", [f"| {self.auth} | migrated | Knowledge/Decisions/auth.md | | ok |",
                                             f"| {self.cache} | migrated | Knowledge/Decisions/cache.md | | ok |",
                                             f"| {self.gone} | obsolete | | removed in a1b2c3d | ok |"])
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("3/3 covered", out)

    def test_wikilinks_left_in_a_target(self):
        self.note("Decisions/auth.md", "See [[cache]].\n\n`[[in code]]`\n")
        self.batch("vault-decisions", "01", [f"| {self.auth} | migrated | Knowledge/Decisions/auth.md | | ok |"])
        _code, out = self.check(batch="01")
        self.assertIn("wikilinks left", out)

    def test_secret_target_under_secrets_dir(self):
        self.write("Resources/secrets/key.pem", "x")
        self.batch("vault-decisions", "01", [f"| {self.auth} | secret | Resources/secrets/key.pem | | ok |",
                                             f"| {self.cache} | secret | Knowledge/Decisions/x.md | | ok |"])
        _code, out = self.check(batch="01")
        self.assertNotIn("key.pem", out)
        self.assertIn("secret target must be under Resources/secrets/", out)

    def test_gate_needs_accepted_handoffs(self):
        self.note("Decisions/auth.md")
        rows = [f"| {self.auth} | migrated | Knowledge/Decisions/auth.md | | ok |",
                f"| {self.cache} | junk | | empty | ok |", f"| {self.gone} | junk | | empty | ok |"]
        self.batch("vault-decisions", "01", rows,
                   "\n## Передача\n\n- #1 → vault-decisions: ~/x — fact\n- #2 vault-decisions: no arrow\n"
                   "\n## Вопросы\n\n- #1 keep it? — context\n- #2 answered — ctx (ответ: yes)\n")
        code, out = self.run_cmd(adopt.cmd_gate)
        self.assertEqual(code, 1, out)
        self.assertIn("handoff vault-decisions/01#1 → vault-decisions is not accepted yet", out)
        self.assertIn("handoff #2 needs a receiving source", out)
        self.assertIn("open question vault-decisions/01#1", out)
        self.assertNotIn("01#2 (", out)
        self.batch("vault-decisions", "01", rows,
                   "\n## Передача\n\n- #1 → vault-decisions: ~/x — fact\n\nпринято: vault-decisions/01#1 → "
                   "Knowledge/Decisions/auth.md\n")
        code, out = self.run_cmd(adopt.cmd_gate)
        self.assertEqual(code, 0, out)
        code, out = self.run_cmd(adopt.cmd_status)
        self.assertIn("vault-decisions (vault): 3/3 covered, 3/3 audited ok", out)
        self.assertIn("open handoffs: 0", out)

    def test_slugmap_and_links(self):
        code, out = self.run_cmd(adopt.cmd_slugmap, force=False)
        self.assertEqual(code, 0, out)
        smap = adopt.read_slugmap(self.task)
        self.assertEqual(smap["2026-01-02-auth"][2], "Knowledge/Decisions/auth.md")
        self.assertEqual(self.run_cmd(adopt.cmd_slugmap, force=False)[0], 1, "no overwrite without --force")
        self.note("Decisions/auth.md", "See [[cache]], [[gone|the old one]], [[2026-01-02-auth#Part]], "
                                       "![[cache]], `[[cache]]` and [x](cache.md).\n\n```\n[[cache]]\n```\n"
                                       "[[nobody]]\n")
        self.batch("vault-decisions", "01", [f"| {self.gone} | obsolete | | removed | ok |"])
        note = self.root / "Knowledge/Decisions/auth.md"
        code, out = self.run_cmd(adopt.cmd_links, notes=[str(note)], write=True)
        self.assertEqual(code, 1, "an unknown key fails")
        text = note.read_text(encoding="utf-8")
        self.assertIn('[cache.md](cache.md "pending")', text)
        self.assertIn("the old one,", text)
        self.assertIn("[T](auth.md)", text, "label: the target note's title")
        self.assertIn('![cache.md](cache.md "pending")', text)
        self.assertIn("`[[cache]]`", text)
        self.assertIn('[x](cache.md "pending")', text)
        self.assertIn("```\n[[cache]]\n```", text)
        self.assertIn("[[nobody]]", text)
        self.assertNotIn("wikilink", " ".join(m for p, lvl, m in self.lint() if p.endswith("auth.md") and lvl == "error"))
        self.note("Decisions/cache.md")
        code, out = self.run_cmd(adopt.cmd_links, notes=[str(note)], write=True)
        self.assertIn("pending link resolved", out)
        self.assertIn("[x](cache.md)", note.read_text(encoding="utf-8"))


class AdoptSources(AdoptProject):
    def git(self, *args: str, cwd: Path | None = None) -> str:
        res = il.run(["git", "-c", "user.name=Unit", "-c", "user.email=unit@example.com", "-c", "commit.gpgsign=false",
                      "-c", "init.defaultBranch=master", *args], cwd=cwd or self.root)
        self.assertEqual(res.returncode, 0, res.stderr)
        return res.stdout

    def make_old(self) -> Path:
        old = self.home / "src" / "appOld"
        server = self.home / "server.git"
        self.git("init", "--bare", "--quiet", str(server), cwd=self.home)
        repo = old / "api"
        repo.mkdir(parents=True)
        self.git("init", "--quiet", cwd=repo)
        (repo / ".gitignore").write_text(".env\n", encoding="utf-8")
        (repo / "README.md").write_text("api\n", encoding="utf-8")
        self.git("add", "-A", cwd=repo)
        self.git("commit", "--quiet", "-m", "init", cwd=repo)
        self.git("remote", "add", "origin", str(server), cwd=repo)
        self.git("push", "--quiet", "origin", "master", cwd=repo)
        self.git("checkout", "--quiet", "-b", "gone", cwd=repo)
        (repo / "g.txt").write_text("g\n", encoding="utf-8")
        self.git("add", "g.txt", cwd=repo)
        self.git("commit", "--quiet", "-m", "gone", cwd=repo)
        self.git("push", "--quiet", "origin", "gone", cwd=repo)
        self.git("checkout", "--quiet", "master", cwd=repo)
        self.git("branch", "-D", "--quiet", "gone", cwd=repo)
        self.git("--git-dir", str(server), "branch", "-D", "--quiet", "gone", cwd=self.home)  # origin/gone is stale now
        self.git("checkout", "--quiet", "-b", "local", cwd=repo)
        (repo / "l.txt").write_text("l\n", encoding="utf-8")
        self.git("add", "l.txt", cwd=repo)
        self.git("commit", "--quiet", "-m", "local", cwd=repo)
        (repo / "README.md").write_text("changed\n", encoding="utf-8")
        (repo / "s.txt").write_text("s\n", encoding="utf-8")
        self.git("add", "s.txt", cwd=repo)
        self.git("stash", "--quiet", cwd=repo)
        (repo / "README.md").write_text("dirty\n", encoding="utf-8")
        (repo / ".env").write_text("X=1\n", encoding="utf-8")
        (repo / "CLAUDE.md").write_text("rules\n", encoding="utf-8")
        (old / "notes.md").write_text("loose\n", encoding="utf-8")
        (old / "CLAUDE.md").write_text("root rules\n", encoding="utf-8")
        (old / "_docs").mkdir()
        (old / "_docs" / "plan.md").write_text("doc\n", encoding="utf-8")
        mem = self.home / ".claude" / "projects" / adopt_sources.claude_dir_name(old) / "memory"
        mem.mkdir(parents=True)
        (mem / "MEMORY.md").write_text("index\n", encoding="utf-8")
        (mem.parent / "11111111-2222-3333-4444-555555555555.jsonl").write_text(json.dumps(
            {"type": "user", "message": {"content": "hi DB_PASSWORD=S3cr3tPassw0rd"}, "cwd": str(old),  # agentic:allow-secret
             "timestamp": "2026-01-01T10:00:00Z"}) + "\n", encoding="utf-8")
        codex = self.home / ".codex" / "sessions" / "2026" / "rollout-x-66666666-7777-8888-9999-000000000000.jsonl"
        codex.parent.mkdir(parents=True)
        codex.write_text(json.dumps({"type": "session_meta", "payload": {"cwd": str(repo)}}) + "\n", encoding="utf-8")
        return old

    def test_inventory_finds_local_work(self):
        old = self.make_old()
        self.start(old)
        out_dir = self.root / "Runtime/adopt/inv"
        code, out = self.run_cmd(adopt_sources.cmd_inventory, roots=[], fetch=False, offline=False, depth=3,
                                 out=str(out_dir), force=False, compare=None)
        self.assertEqual(code, 0, out)
        detail = (out_dir / "details" / "appOld__api.txt").read_text(encoding="utf-8")
        self.assertIn("local +1 (local-only)", detail)
        self.assertIn("origin/gone +1", detail)
        self.assertIn("stash@{0}", detail)
        self.assertIn("M README.md", detail)
        self.assertIn("!! .env", detail)
        self.assertIn("?? CLAUDE.md", detail)
        self.assertIn("appOld/_docs", (out_dir / "nongit.tsv").read_text(encoding="utf-8"))
        self.assertIn("| appOld/api |", (out_dir / "resources.md").read_text(encoding="utf-8"))
        self.assertEqual(self.git("status", "--porcelain", cwd=old / "api").count("README.md"), 1)
        (old / "api" / "new.txt").write_text("n\n", encoding="utf-8")
        code, out = self.run_cmd(adopt_sources.cmd_inventory, roots=[], fetch=False, offline=True, depth=3,
                                 out=str(self.root / "Runtime/adopt/inv2"), force=False, compare=str(out_dir))
        self.assertEqual(code, 1, out)
        self.assertIn("changed: appOld/api", out)

    def test_sources_and_manifests(self):
        old = self.make_old()
        self.start(old)
        code, out = self.run_cmd(adopt_sources.cmd_sources, vault=[])
        self.assertEqual(code, 0, out)
        self.assertIn('kind = "claude-memory"', out)
        self.assertIn('# kind = "transcripts"', out)
        self.assertIn('codex_cwd = ["~/src/appOld"]', out)
        self.assertIn('name = "appold-docs"', out)
        self.assertIn('kind = "agent-files"', out)
        self.assertIn('kind = "loose-docs"', out)
        task = self.add_sources('[[source]]\nname = "docs"\nkind = "docs"\npaths = ["~/src/appOld/_docs"]\n\n'
                                '[[source]]\nname = "agent-files"\nkind = "agent-files"\n\n'
                                '[[source]]\nname = "loose"\nkind = "loose-docs"\n\n'
                                '[[source]]\nname = "talks"\nkind = "transcripts"\n'
                                f'paths = ["~/.claude/projects/{adopt_sources.claude_dir_name(old)}*"]\n'
                                'codex_cwd = ["~/src/appOld"]\n')
        code, out = self.run_cmd(adopt.cmd_manifest, source=None)
        self.assertEqual(code, 0, out)
        self.assertEqual(adopt.read_manifest(task, "agent-files"),
                         ["~/src/appOld/CLAUDE.md", "~/src/appOld/api/CLAUDE.md"])
        self.assertEqual(adopt.read_manifest(task, "loose"), ["~/src/appOld/notes.md"])
        talks = adopt.read_manifest(task, "talks")
        self.assertEqual(len(talks), 2, talks)
        code, out = self.run_cmd(adopt_sources.cmd_digest, source="talks")
        self.assertEqual(code, 0, out)
        digests = self.root / "Runtime/adopt/digests/talks"
        text = (digests / "11111111-2222-3333-4444-555555555555.md").read_text(encoding="utf-8")
        self.assertNotIn("S3cr3tPassw0rd", text)
        self.assertIn("11111111-2222-3333-4444-555555555555\t", (digests / "_secrets.tsv").read_text(encoding="utf-8"))

    def test_refs_report_locations_only(self):
        old = self.make_old()
        self.start(old)
        (self.home / ".gitconfig").write_text(f'[includeIf "gitdir:{old}/"]\n  path = {old}/.gitconfig\n',
                                             encoding="utf-8")
        (self.home / ".claude.json").write_text(json.dumps({"projects": {str(old): {"token": "x"}}}), encoding="utf-8")
        found = adopt_sources.scan_refs([old])
        self.assertIn(f"~/.gitconfig:1: {old}", found)
        self.assertIn(f"~/.claude.json: /projects/{old}", found)


class AdoptArchive(AdoptProject):
    def test_archive_is_verified_private_and_never_overwritten(self):
        src = self.home / "vault"
        (src / "a").mkdir(parents=True)
        (src / "a" / "x.md").write_text("x\n", encoding="utf-8")
        (src / "y.bin").write_bytes(b"\0\1")
        (src / "link").symlink_to("a")
        self.start()
        code, out = self.run_cmd(adopt.cmd_archive, name="old-vault", paths=[str(src)], dir=None)
        self.assertEqual(code, 0, out)
        self.assertIn("2 files verified", out)
        dest = self.home / "Archive" / "old-vault.tgz"
        if os.name != "nt":
            self.assertEqual(dest.stat().st_mode & 0o777, 0o600)
        code, out = self.run_cmd(adopt.cmd_archive, name="old-vault", paths=[str(src)], dir=None)
        self.assertEqual(code, 1)
        self.assertIn("already exists", out)
        code, out = self.run_cmd(adopt.cmd_archive, name="inside", paths=[str(src)], dir=str(self.root / "Runtime"))
        self.assertIn("outside the project", out)


class KbReminders(KnowledgeProject):
    R = "Knowledge/Reminders/r.md"

    def test_lint(self):
        self.note("Plans/p.md")
        self.note("Reminders/r.md", "[P](../Plans/p.md)\n", front="due: 2026-11-01\n")
        self.assertEqual([p for p in self.lint() if p[0] == self.R], [])
        self.note("Reminders/r.md", "Nothing linked\n", front="due: soon\n")
        problems = [p[1:] for p in self.lint() if p[0] == self.R]
        self.assertIn(("error", "'due' is not a valid date (expected YYYY-MM-DD): 'soon'"), problems)
        self.assertIn(("warning", "reminder links to no note: link the notes to consider"), problems)
        self.note("Plans/p.md", front="due: 2026-11-01\n")
        self.assertIn(("Knowledge/Plans/p.md", "warning", "'due' is meant for reminder notes"), self.lint())

    def test_stale(self):
        self.note("Plans/p.md", front=f"verified: {date.today().isoformat()}\n")
        today = date.today()
        cases = {"past": "due: 2020-01-01\n", "future": "due: 2999-01-01\n", "old": "verified: 2020-01-01\n"}
        for slug, front in cases.items():
            self.note(f"Reminders/{slug}.md", "[P](../Plans/p.md)\n", front=front)
        found = {n.slug: kb.stale_reason(n, today, None) for n in kb.load_notes()}
        self.assertIn("reminder due", found["past"][1])
        self.assertIsNone(found["future"])
        self.assertIn("threshold 14", found["old"][1])
        self.assertIsNone(found["p"])

    def test_found_by_the_words_of_its_targets(self):
        self.note("Plans/p.md", front="aliases: [billing]\n")
        self.note("Reminders/r.md", "[P](../Plans/p.md)\n")
        hits = kb.run_search("billing", kb.load_notes(), types={"reminder"})
        self.assertEqual([h.note.rel for h in hits], [self.R])


class KbNearby(KnowledgeProject):
    def test_ranks_by_resource_links_and_words(self):
        self.note("Tasks/t.md", front="resources: [api/src/billing]\ntags: [billing]\n")
        self.note("Plans/same-module.md", front="resources: [api/src/billing/invoice]\n")
        self.note("Plans/other.md", front="resources: [web]\n")
        self.note("Plans/words.md", front="tags: [billing]\naliases: [invoices]\n")
        self.note("Reminders/r.md", "[T](../Tasks/t.md)\n")
        self.note("Gotchas/g.md", front="resources: [api/src/billing]\n")
        self.write("Knowledge/Tasks/done.md", "---\ntype: task\nstatus: done\ntitle: T\ndescription: D\n"
                                              "created: 2026-01-01\nresources: [api/src/billing]\n---\n")
        notes = kb.load_notes()
        task = next(n for n in notes if n.slug == "t")
        found = {x.note.slug: x for x in kb.find_nearby([task], notes)}
        self.assertEqual(set(found), {"same-module", "r", "words"})
        self.assertIn("resource api/src/billing", found["same-module"].reasons)
        self.assertIn("links to Knowledge/Tasks/t.md", found["r"].reasons)
        self.assertIn("tags: billing", found["words"].reasons)
        by_query = kb.find_nearby([], notes, query="invoices")
        self.assertEqual([x.note.slug for x in by_query], ["words"])


class KbHooks(KnowledgeProject):
    def setUp(self):
        super().setUp()
        import hook
        self.hook = hook

    def run_hook(self, func, data, agent="claude") -> str:
        import argparse
        import contextlib
        import io

        saved = self.hook.read_input
        self.hook.read_input = lambda: data
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                func(argparse.Namespace(agent=agent))
        finally:
            self.hook.read_input = saved
        return buf.getvalue()

    def test_suggest_lists_reminders_apart(self):
        self.note("Plans/p.md", front="aliases: [billing, invoices]\n")
        self.note("Reminders/r.md", "[P](../Plans/p.md)\n")
        notes, reminders = self.hook.suggest_all("billing invoices refactoring")
        self.assertEqual([p for p, _ in notes], ["Knowledge/Plans/p.md"])
        self.assertEqual([p for p, _ in reminders], ["Knowledge/Reminders/r.md"])

    def test_edited_paths(self):
        data = {"cwd": str(self.root), "tool_input": {"file_path": str(self.root / "Knowledge/Plans/p.md")}}
        self.assertEqual(self.hook.edited_paths(data), ["Knowledge/Plans/p.md"])
        patch = ("*** Begin Patch\n*** Update File: Knowledge/Gotchas/g.md\n@@\n-a\n+b\n"
                 "*** Add File: Toolbox/x.py\n+x\n*** End Patch\n")
        self.assertEqual(self.hook.edited_paths({"cwd": str(self.root), "tool_input": {"command": patch}}),
                         ["Knowledge/Gotchas/g.md"])
        self.assertEqual(self.hook.edited_paths({"tool_input": {"file_path": "Knowledge/.obsidian/x.json"}}), [])

    def test_track_then_ask_once_to_commit(self):
        self.git("init", "--quiet")
        self.note("Plans/p.md")
        data = {"session_id": "s1", "cwd": str(self.root),
                "tool_input": {"file_path": "Knowledge/Plans/p.md"}}
        self.run_hook(self.hook.kb_track, data)
        stop = {"session_id": "s1"}
        out = json.loads(self.run_hook(self.hook.kb_uncommitted, stop))
        self.assertEqual(out["decision"], "block")
        self.assertIn("Knowledge/Plans/p.md", out["reason"])
        self.assertEqual(self.run_hook(self.hook.kb_uncommitted, stop), "", "asks once per state")
        self.assertEqual(self.run_hook(self.hook.kb_uncommitted, {"session_id": "s2"}), "", "other session")
        self.assertEqual(self.run_hook(self.hook.kb_uncommitted, {**stop, "stop_hook_active": True}), "")
        self.git("add", "--", "Knowledge/Plans/p.md")
        self.git("commit", "-q", "-m", "x")
        self.assertEqual(self.run_hook(self.hook.kb_uncommitted, stop), "")


class KbCommit(KnowledgeProject):
    def setUp(self):
        super().setUp()
        import kb_git
        self.kb_git = kb_git
        saved = os.environ.get(kb_git.SESSION_OVERRIDE)
        self.addCleanup(lambda: os.environ.pop(kb_git.SESSION_OVERRIDE, None) if saved is None
                        else os.environ.__setitem__(kb_git.SESSION_OVERRIDE, saved))
        self.session("claude:A")
        self.git("init", "--quiet")
        self.git("config", "user.name", "Unit")
        self.git("config", "user.email", "unit@example.com")
        hook = self.write(".agents/git-hooks/pre-commit", "#!/bin/sh\nexit 0\n")
        hook.chmod(0o755)
        self.write("README.md", "x\n")
        self.git("add", "README.md")
        self.git("commit", "-q", "-m", "init")

    def session(self, value: str) -> None:
        os.environ[self.kb_git.SESSION_OVERRIDE] = value

    def commit(self, *paths: str, message: list[str] | None = None, amend: bool = False) -> tuple[int, str]:
        return self.tb(self.kb_git.cmd_commit, paths=list(paths), message=message, amend=amend)

    def log(self) -> list[str]:
        res = il.run(["git", "log", "--format=%s|%(trailers:key=Agent-Session,valueonly)"], cwd=self.root)
        return [line for line in res.stdout.splitlines() if line]

    def test_needs_hooks(self):
        self.note("Plans/a.md")
        code, out = self.commit("Knowledge/Plans/a.md", message=["Plan a"])
        self.assertEqual(code, 1)
        self.assertIn("tb setup", out)

    def test_commit_amend_fixup_squash(self):
        self.git("config", "core.hooksPath", ".agents/git-hooks")
        self.assertEqual(self.commit("README.md", message=["x"])[0], 2, "only Knowledge/")
        self.note("Plans/a.md")
        self.note("Plans/foreign.md")
        self.git("add", "--", "Knowledge/Plans/foreign.md")  # staged by another session
        code, out = self.commit("Plans/a.md", message=["Plan a", "- why"])
        self.assertEqual(code, 0, out)
        self.assertEqual(self.log()[0], "knowledge: Plan a|claude:A")
        staged = il.run(["git", "diff", "--cached", "--name-only"], cwd=self.root).stdout.split()
        self.assertEqual(staged, ["Knowledge/Plans/foreign.md"], "the other session's index is kept")

        self.assertIn("tb kb session title", out, "hint to set a title")
        code, out = self.tb(self.kb_git.cmd_session, session_command="title", text=["Plan", " work "])
        self.assertEqual((code, out.strip()), (0, "Agent-Session: claude:A (Plan work)"))
        self.note("Plans/a.md", "Fixed\n")
        code, out = self.commit("Knowledge/Plans/a.md", amend=True)
        self.assertEqual(code, 0, out)
        self.assertIn("Amended", out)
        self.assertEqual(len(self.log()), 2)

        self.session("claude:B")
        self.assertEqual(self.commit("Knowledge/Plans/foreign.md", message=["Foreign"])[0], 0)
        self.session("claude:A")
        self.note("Plans/a.md", "Fixed again\n")
        code, out = self.commit("Knowledge/Plans/a.md", amend=True)
        self.assertEqual(code, 0, out)
        self.assertIn("Fixup committed", out)
        self.assertEqual(self.log()[0], "fixup! knowledge: Plan a|claude:A (Plan work)")

        self.note("Plans/b.md")
        code, out = self.commit("Knowledge/Plans/b.md", amend=True)
        self.assertEqual(code, 2, "nothing of this session to correct and no message")

        self.write("README.md", "dirty\n")
        self.assertEqual(self.tb(self.kb_git.cmd_squash, dry_run=False)[0], 1, "dirty tree")
        self.write("README.md", "x\n")
        code, out = self.tb(self.kb_git.cmd_squash, dry_run=False)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.log(), ["knowledge: Foreign|claude:B", "knowledge: Plan a|claude:A", "init|"],
                         "amend without -m keeps the message written before the title was set")
        shown = il.run(["git", "show", "HEAD~1:Knowledge/Plans/a.md"], cwd=self.root).stdout
        self.assertIn("Fixed again", shown)

    def test_deleted_note(self):
        self.git("config", "core.hooksPath", ".agents/git-hooks")
        self.note("Plans/a.md")
        self.assertEqual(self.commit("Knowledge/Plans/a.md", message=["Plan a"])[0], 0)
        (self.root / "Knowledge/Plans/a.md").unlink()
        code, out = self.commit("Knowledge/Plans/a.md", message=["Drop plan a"])
        self.assertEqual(code, 0, out)
        files = il.run(["git", "ls-files", "Knowledge"], cwd=self.root).stdout
        self.assertEqual(files, "")


class HookMatchers(_ToolboxProject):
    HOOKS = ('[[hook]]\nname = "kb-track"\nevent = "after-tool"\ntools = "edit"\n\n'
             '[[hook]]\nname = "kb-uncommitted"\nevent = "stop"\n')

    def render(self, agent: str) -> tuple[dict, list[str]]:
        import adapters
        manifest = resources.common.load_toml(
            TEMPLATE_ROOT / "payload/modules/core/.agents/adapters" / agent / "adapter.toml")
        ctx = adapters.load_context(self.root, agent, manifest)
        return adapters.render(ctx), ctx.warnings

    def test_matcher_or_skip(self):
        self.write(".agents/hooks/hooks.toml", self.HOOKS)
        files, warnings = self.render("claude")
        hooks = json.loads(files[".claude/settings.json"])["hooks"]
        self.assertEqual(hooks["PostToolUse"][0]["matcher"], "Write|Edit|MultiEdit|NotebookEdit")
        self.assertNotIn("matcher", hooks["Stop"][0])
        self.assertEqual(warnings, [])
        files, warnings = self.render("codex")
        hooks = json.loads(files[".codex/hooks.json"])["hooks"]
        self.assertNotIn("PostToolUse", hooks)
        self.assertIn("Stop", hooks)
        self.assertTrue(any("kb-track" in w for w in warnings), warnings)


class MigrationCommitHooks(unittest.TestCase):
    def test_appends_missing_hooks_once(self):
        migration = TEMPLATE_ROOT / il.MIGRATIONS_DIR / "0.5.0_knowledge-commit-hooks.py"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            il.run_migration(migration, root)  # no hooks.toml: nothing to do
            self.assertFalse((root / ".agents").exists())
            path = root / ".agents/hooks/hooks.toml"
            path.parent.mkdir(parents=True)
            path.write_text('[[hook]]\nname = "kb-suggest"\nevent = "prompt-submit"\n\n'
                            '[[hook]]\nname = "kb-track"\nevent = "after-tool"\n', encoding="utf-8")
            il.run_migration(migration, root)
            first = path.read_text(encoding="utf-8")
            self.assertEqual(first.count('name = "kb-track"'), 1)
            self.assertEqual(first.count('name = "kb-uncommitted"'), 1)
            il.run_migration(migration, root)
            self.assertEqual(path.read_text(encoding="utf-8"), first)
            import tomllib
            self.assertEqual(len(tomllib.loads(first)["hook"]), 3)


if __name__ == "__main__":
    os.environ.setdefault("AGENTIC_ROOT", str(TEMPLATE_ROOT))
    unittest.main(verbosity=1)
