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


if __name__ == "__main__":
    os.environ.setdefault("AGENTIC_ROOT", str(TEMPLATE_ROOT))
    unittest.main(verbosity=1)
