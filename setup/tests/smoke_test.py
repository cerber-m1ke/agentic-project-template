# /// script
# requires-python = ">=3.12"
# dependencies = ["tomli-w>=1", "pyyaml>=6"]
# [tool.uv]
# exclude-newer = "2026-10-01T00:00:00Z"
# ///
"""End-to-end smoke test: release -> clone -> init -> tb commands -> module adopt (init, ledgers, gate,
removal) -> next release -> update
(conflicts, removal, seeded changes, a new module, a language switch) -> a project initialized from
a development state receives the release.

    TB_ROOT=<template> payload/modules/core/Toolbox/tb run setup/tests/smoke_test.py [--keep]

Works on a copy of the template working tree in a temporary folder (the copy acts as the remote
repository; nothing in the template itself is touched). UV_* variables already set (by tb or by
the caller) are passed through, so the nested project reuses the same Python and package cache;
the uv running this script is put on PATH so the project's tb does not download another one.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

TEMPLATE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(TEMPLATE_ROOT / "setup"))
sys.dont_write_bytecode = True
import installer_lib as il  # noqa: E402

COPY_EXCLUDE_ANYWHERE = {".git", "__pycache__", ".DS_Store"}
COPY_EXCLUDE_TOP = {"Runtime", "CLAUDE.md"}
PAYLOAD_JUNK = ("payload/modules/core/Runtime/tools/junk-from-payload.txt",
                "payload/modules/core/.idea/junk-from-payload.xml",
                "payload/modules/knowledge/Knowledge/.obsidian/junk-from-payload.json")
WINDOWS = os.name == "nt"
NAME = "demo"
AGENTS = ["claude", "codex"]
NOTE_TITLE = "Прокси ломает загрузку uv"
NOTE_PATH = "Knowledge/Gotchas/uv-proxy.md"


class Stop(Exception):
    """A step failed in a way that makes the following steps meaningless."""

    def __init__(self, message: str, recorded: bool = False) -> None:
        super().__init__(message)
        self.recorded = recorded


class Results:
    def __init__(self) -> None:
        self.items: list[tuple[bool, str, str]] = []

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.items.append((bool(ok), name, detail))
        mark = "PASS" if ok else "FAIL"
        print(f"{mark}  {name}" + (f" — {detail}" if detail and not ok else ""), flush=True)
        return bool(ok)

    def require(self, name: str, ok: bool, detail: str = "") -> None:
        if not self.check(name, ok, detail):
            raise Stop(name, recorded=True)

    @property
    def failed(self) -> int:
        return sum(1 for ok, _n, _d in self.items if not ok)


R = Results()


def tail(text: str, lines: int = 15) -> str:
    rows = [r for r in (text or "").strip().splitlines() if r.strip()]
    return (" | ".join(rows[-lines:]))[-1500:]


def run(cmd: list[str], cwd: Path, env: dict, timeout: int = 600) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, cwd=cwd, env=env, text=True, encoding="utf-8", errors="replace",
                              capture_output=True, stdin=subprocess.DEVNULL, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(cmd, 124, exc.stdout or "", f"timeout after {timeout}s")


def output(res: subprocess.CompletedProcess) -> str:
    return (res.stdout or "") + (res.stderr or "")


def git(*args: str, cwd: Path, env: dict) -> str:
    res = run(["git", *args], cwd, env, timeout=120)
    if res.returncode != 0:
        raise Stop(f"git {' '.join(args)} failed in {cwd}: {tail(output(res))}")
    return res.stdout.strip()


def make_env(work: Path) -> dict:
    env = {k: v for k, v in os.environ.items()
           if k not in ("TB_ROOT", "AGENTIC_ROOT", "VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME",
                        "UV_RUN_RECURSION_DEPTH", "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
    gitconfig = work / "gitconfig"
    gitconfig.write_text("[user]\n\tname = Smoke Test\n\temail = smoke@example.com\n"
                         "[init]\n\tdefaultBranch = master\n[commit]\n\tgpgsign = false\n"
                         "[tag]\n\tgpgsign = false\n[protocol \"file\"]\n\tallow = always\n",
                         encoding="utf-8")
    env.update(GIT_CONFIG_GLOBAL=str(gitconfig), GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0",
               PYTHONUTF8="1")
    uv_dirs = []
    if os.environ.get("UV"):
        uv_dirs.append(str(Path(os.environ["UV"]).parent))
    local_uv = TEMPLATE_ROOT / "Runtime" / "tools" / "uv"
    if local_uv.is_dir():
        uv_dirs.append(str(local_uv))
    env["PATH"] = os.pathsep.join([*uv_dirs, env.get("PATH", "")])
    return env


def copy_template(dst: Path) -> None:
    def ignore(directory: str, names: list[str]) -> list[str]:
        top = Path(directory).resolve() == TEMPLATE_ROOT
        return [n for n in names if n in COPY_EXCLUDE_ANYWHERE or (top and n in COPY_EXCLUDE_TOP)]

    shutil.copytree(TEMPLATE_ROOT, dst, ignore=ignore, symlinks=True)


def tb_cmd(project: Path) -> list[str]:
    if WINDOWS:
        return ["cmd", "/c", str(project / "Toolbox" / "tb.cmd")]
    return ["sh", str(project / "Toolbox" / "tb")]


def payload_sources(origin: Path, module: str, dest: str) -> list[Path]:
    """Payload files (all language variants) that install to `dest`."""
    d = Path(dest)
    base = origin / il.MODULES_DIR / module / d.parent
    candidates = [base / d.name] + [base / f"{d.stem}.{lang}{d.suffix}" for lang in il.LANGS]
    return [p for p in candidates if p.is_file()]


def insert_after_marker(text: str, line: str) -> str:
    lines = text.split("\n")
    for i, row in enumerate(lines):
        if "agentic:begin" in row:
            lines.insert(i + 1, line)
            return "\n".join(lines)
    raise Stop("no agentic:begin marker in AGENTS payload")


def bump_minor(version: str) -> str:
    major, minor, _patch, _release = il.parse_version(version)
    return f"{major}.{minor + 1}.0"


def release_of(version: str) -> str:
    return version.removesuffix("-dev")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


# --- stages -------------------------------------------------------------------------------------

def stage_release(origin: Path, env: dict) -> tuple[str, str]:
    copy_template(origin)
    version = release_of(il.read_version(origin))  # the working tree is X.Y.Z-dev between releases
    (origin / il.VERSION_FILE).write_text(version + "\n", encoding="utf-8")
    git("init", "--quiet", cwd=origin, env=env)
    git("symbolic-ref", "HEAD", "refs/heads/master", cwd=origin, env=env)
    git("add", "-A", cwd=origin, env=env)
    git("commit", "--quiet", "--no-verify", "-m", f"release v{version}", cwd=origin, env=env)
    git("tag", f"v{version}", cwd=origin, env=env)
    R.check(f"template copy released as v{version}", True)
    return version, git("rev-parse", "HEAD", cwd=origin, env=env)


def stage_refusals(origin: Path, work: Path, env: dict) -> None:
    """init must refuse unsafe folders and bad names before changing anything."""
    def init(folder: Path, *args: str) -> subprocess.CompletedProcess:
        return run([sys.executable, str(folder / "setup" / "init.py"), *args], folder, env, timeout=300)

    main_clone, linked = work / "refuse-main", work / "refuse-worktree"
    git("clone", "--quiet", str(origin), str(main_clone), cwd=work, env=env)
    git("worktree", "add", "--quiet", "--detach", str(linked), cwd=main_clone, env=env)
    res = init(linked, "--name", NAME, "--yes")
    dot_git = linked / ".git"
    R.check("init refuses when .git is a file (worktree)",
            res.returncode == 1 and "worktree" in output(res) and (linked / "setup").is_dir()
            and dot_git.is_file() and os.access(dot_git, os.R_OK), tail(output(res)))

    # The payload copy of tb is not a project's tb: without TB_ROOT it refuses (a hook stays silent)
    # instead of putting Runtime/ into the payload.
    payload_tb = main_clone / "payload" / "modules" / "core" / "Toolbox"
    payload_cmd = (["cmd", "/c", str(payload_tb / "tb.cmd")] if WINDOWS else ["sh", str(payload_tb / "tb")])
    res = run([*payload_cmd, "version"], main_clone, env, timeout=300)
    R.check("payload tb refuses to run without TB_ROOT",
            res.returncode == 1 and "TB_ROOT" in output(res)
            and not (payload_tb.parent / "Runtime").exists(), tail(output(res)))
    res = run([*payload_cmd, "hook", "kb-suggest", "--agent", "claude"], main_clone, env, timeout=300)
    R.check("payload tb: a hook exits 0", res.returncode == 0 and not (payload_tb.parent / "Runtime").exists(),
            tail(output(res)))

    unpacked = work / "refuse-unpacked"
    shutil.copytree(origin, unpacked, ignore=shutil.ignore_patterns(".git"), symlinks=True)
    res = init(unpacked, "--name", NAME, "--dry-run")
    R.check("init accepts an unpacked template (no .git) in a dry run", res.returncode == 0, tail(output(res)))
    (unpacked / "foreign.txt").write_text("not from the template\n", encoding="utf-8")
    res = init(unpacked, "--name", NAME, "--yes")
    R.check("init refuses foreign files without --force",
            res.returncode == 1 and "foreign.txt" in output(res) and (unpacked / "setup").is_dir(),
            tail(output(res)))
    res = init(unpacked, "--name", NAME, "--force", "--dry-run")
    R.check("init --force lists foreign files", res.returncode == 0 and "foreign.txt" in output(res),
            tail(output(res)))
    for bad in ('bad"name', "bad\\name", "bad\tname"):
        res = init(unpacked, "--name", bad, "--force", "--yes")
        R.check(f"init rejects project name {bad!r}",
                res.returncode == 1 and "invalid project name" in output(res) and (unpacked / "setup").is_dir(),
                tail(output(res)))


def stage_init(origin: Path, project: Path, env: dict, version: str, commit: str) -> dict:
    git("clone", "--quiet", str(origin), str(project), cwd=origin.parent, env=env)
    # Leftovers that the template's .gitignore hides must not end up in the initial commit, and a
    # repository-local identity must survive the replacement of .git.
    if not WINDOWS:
        os.symlink("AGENTS.md", project / "CLAUDE.md")
    (project / ".idea").mkdir()
    (project / ".idea" / "workspace.xml").write_text("<project/>\n", encoding="utf-8")
    # Files that git ignores inside payload/ are not template files and must not be installed.
    for junk in PAYLOAD_JUNK:
        (project / junk).parent.mkdir(parents=True, exist_ok=True)
        (project / junk).write_text("junk\n", encoding="utf-8")
    git("config", "user.name", "Local Smoke", cwd=project, env=env)
    args = ["--name", NAME, "--profile", "software", "--language", "ru", "--agents", ",".join(AGENTS), "--yes"]
    if WINDOWS:
        cmd = ["cmd", "/c", str(project / "init.cmd"), *args]
    else:
        cmd = ["sh", str(project / "init.sh"), *args]
    res = run(cmd, project, env, timeout=1200)
    R.require("init: exit code 0", res.returncode == 0, tail(output(res)))

    lock_path = project / il.LOCK_PATH
    R.require("init: agentic.lock written", lock_path.is_file())
    lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    tpl, prj = lock.get("template", {}), lock.get("project", {})
    R.check("lock: schema/template", lock.get("schema") == 1 and tpl.get("version") == version
            and tpl.get("commit") == commit and Path(tpl.get("source", "")).resolve() == origin.resolve(),
            f"{tpl}")
    R.check("lock: project", prj.get("name") == NAME and prj.get("language") == "ru"
            and prj.get("profile") == "software"
            and prj.get("modules") == ["core", "knowledge", "resources", "obsidian"], f"{prj}")
    files = lock.get("files", {})
    bad = []
    for path, rec in files.items():
        local = il.local_hash(project / path, rec.get("class", "managed"))
        if local != rec.get("sha256"):
            bad.append(path)
    R.check(f"lock: {len(files)} file hashes match the project", files and not bad, f"mismatch: {bad[:5]}")
    junk_installed = [p for p in files if "junk-from-payload" in p]
    junk_installed += [p for p in ("Runtime/tools/junk-from-payload.txt", ".idea/junk-from-payload.xml",
                                   "Knowledge/.obsidian/junk-from-payload.json") if (project / p).exists()]
    R.check("init: files that git ignores in payload/ are not installed", not junk_installed, f"{junk_installed}")
    leftovers = [p for p in ("setup", "payload", "init.sh", "init.cmd", "README.en.md", "CHANGELOG.md")
                 if (project / p).exists()]
    R.check("init: installer removed", not leftovers, f"left: {leftovers}")
    with_placeholders = []
    for path in project.rglob("*"):
        rel = path.relative_to(project).as_posix()
        if rel.split("/")[0] in (".git", "Runtime") or not path.is_file():
            continue
        data = path.read_bytes()
        if il.is_text(data) and "{{agentic." in data.decode("utf-8"):
            with_placeholders.append(rel)
    R.check("init: no {{agentic.*}} placeholders left", not with_placeholders, f"{with_placeholders[:5]}")
    count = git("rev-list", "--count", "HEAD", cwd=project, env=env)
    subject = git("log", "-1", "--format=%s", cwd=project, env=env)
    R.check("git: exactly one commit", count == "1" and subject == f"agentic: init from template v{version}",
            f"{count} commit(s), last: {subject}")
    R.check("git: branch master", git("branch", "--show-current", cwd=project, env=env) == "master")
    tracked = git("ls-files", cwd=project, env=env).splitlines()
    R.check("init: commits payload files only (no template leftovers)",
            "CLAUDE.md" not in tracked and not any(t.startswith(".idea/") for t in tracked)
            and il.LOCK_PATH in tracked and set(lock_files_of(project)) <= set(tracked),
            f"{[t for t in tracked if t in ('CLAUDE.md',) or t.startswith('.idea/')]}")
    author = git("log", "-1", "--format=%an", cwd=project, env=env)
    R.check("init: repository-local git identity kept", author == "Local Smoke", author)
    claude_md = read(project / "CLAUDE.md")
    R.check("claude: CLAUDE.md is generated and imports AGENTS.md",
            "@AGENTS.md" in claude_md and not (project / "CLAUDE.md").is_symlink()
            and "@AGENTS.md" not in read(project / "AGENTS.md"), claude_md[:200])
    R.check("git: clean tree after init and setup", git("status", "--porcelain", cwd=project, env=env) == "",
            git("status", "--porcelain", cwd=project, env=env)[:300])
    R.check("git: core.hooksPath", git("config", "core.hooksPath", cwd=project, env=env) == ".agents/git-hooks")
    modes = git("ls-files", "-s", "--", "Toolbox/tb", ".agents/git-hooks/pre-commit", cwd=project, env=env)
    R.check("git: executables have mode 100755",
            len(modes.splitlines()) == 2 and all(m.startswith("100755") for m in modes.splitlines()), modes)
    local = tomllib.loads(read(project / ".agents" / "local.toml") or "")
    R.check("setup: .agents/local.toml lists the agents", local.get("agents") == AGENTS, f"{local}")
    skills = sorted(p.name for p in (project / ".agents" / "skills").iterdir() if p.is_dir())
    broken = [s for s in skills
              if not ((project / ".claude" / "skills" / s / "SKILL.md").is_file()
                      and il_is_link(project / ".claude" / "skills" / s))]
    R.check(f"claude: .claude/skills/<name> links ({len(skills)})", skills and not broken, f"broken: {broken}")
    subagents = sorted(p.stem for p in (project / ".agents" / "agents").glob("*.md"))
    missing = [f".codex/agents/{s}.toml" for s in subagents if not (project / ".codex" / "agents" / f"{s}.toml").is_file()]
    missing += [p for p in (".codex/config.toml", ".codex/hooks.json") if not (project / p).is_file()]
    R.check("codex: generated .codex/ files", not missing, f"missing: {missing}")
    for path in (".codex/hooks.json", ".claude/settings.json"):
        try:
            json.loads(read(project / path))
            ok = True
        except json.JSONDecodeError:
            ok = False
        R.check(f"adapters: {path} is valid JSON", ok)
    R.check("obsidian: Knowledge/.obsidian created", (project / "Knowledge" / ".obsidian").is_dir())
    imls = sorted((project / ".idea").glob("*.iml"))
    R.check("ide: JetBrains module excludes Resources and Runtime",
            len(imls) == 1 and all(f'url="file://$MODULE_DIR$/{n}"' in read(imls[0]) for n in ("Resources", "Runtime")),
            f"{imls}")
    try:
        vscode = json.loads(read(project / ".vscode" / "settings.json"))
    except (OSError, json.JSONDecodeError):
        vscode = {}
    R.check("ide: VS Code search and watcher exclude Resources and Runtime",
            all(vscode.get(k, {}).get(f"{n}/**") is True
                for k in ("search.exclude", "files.watcherExclude") for n in ("Resources", "Runtime")), f"{vscode}")
    return lock


def origin_of(project: Path) -> str:
    """Template source recorded in the project's lock."""
    return tomllib.loads(read(project / il.LOCK_PATH) or "")["template"]["source"]


def lock_files_of(project: Path) -> list[str]:
    return list(tomllib.loads(read(project / il.LOCK_PATH) or "").get("files", {}))


def il_is_link(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def stage_toolbox(project: Path, env: dict, work: Path) -> None:
    tb = tb_cmd(project)
    description = "Без HTTPS_PROXY uv не может скачать Python и пакеты за корпоративным прокси"
    res = run([*tb, "kb", "new", "gotcha", "uv-proxy", "--title", NOTE_TITLE, "--description", description],
              project, env)
    note = project / NOTE_PATH
    R.check("tb kb new gotcha --description", res.returncode == 0 and note.is_file()
            and f'description: "{description}"' in read(note), tail(output(res)))
    if note.is_file():
        text = read(note).rstrip("\n") + ("\n\nЗа корпоративным прокси загрузка uv и Python падает с "
                                          "таймаутом. Решение: задать HTTPS_PROXY перед запуском Toolbox/tb.\n")
        il.write_file(project, NOTE_PATH, text.encode("utf-8"), text=True)
    res = run([*tb, "kb", "lint"], project, env)
    R.check("tb kb lint", res.returncode == 0, tail(output(res)))
    res = run([*tb, "kb", "search", "прокси", "загрузки"], project, env)
    R.check("tb kb search (Russian morphology)", res.returncode == 0 and NOTE_PATH in res.stdout,
            tail(output(res)))
    res = run([*tb, "agents", "doctor"], project, env)
    R.check("tb agents doctor", res.returncode == 0, tail(output(res)))
    stage_permissions(project, env)
    stage_hook_and_root(project, env, work)

    # A resource: local bare repository with one commit.
    src, bare = work / "lib-src", work / "remotes" / "lib.git"
    src.mkdir()
    git("init", "--quiet", cwd=src, env=env)
    (src / "README.md").write_text("# lib\n", encoding="utf-8")
    git("add", "README.md", cwd=src, env=env)
    git("commit", "--quiet", "-m", "init", cwd=src, env=env)
    bare.parent.mkdir()
    git("clone", "--quiet", "--bare", str(src), str(bare), cwd=work, env=env)
    res = run([*tb, "resources", "add", bare.as_posix(), "--name", "lib", "--description", "Test library",
               "--clone"], project, env)
    catalog = read(project / "Resources" / "resources.toml")
    R.check("tb resources add --clone", res.returncode == 0 and "lib" in catalog
            and (project / "Resources" / "lib" / "README.md").is_file(), tail(output(res)))
    res = run([*tb, "resources", "status"], project, env)
    R.check("tb resources status", res.returncode == 0 and "lib" in res.stdout, tail(output(res)))
    # Agent settings inside a resource: reported until marked as reviewed with `tb resources set`.
    (project / "Resources" / "lib" / ".mcp.json").write_text("{}\n", encoding="utf-8")
    res = run([*tb, "resources", "status"], project, env)
    hint = "Toolbox/tb resources set lib agent_settings_reviewed=.mcp.json"
    R.check("tb resources status: reports unreviewed agent settings with a set hint",
            res.returncode == 0 and hint in res.stdout, tail(output(res)))
    res = run([*tb, "resources", "set", "lib", "agent_settings_reviewed=.mcp.json", "description=Library"],
              project, env)
    after = run([*tb, "resources", "status"], project, env)
    R.check("tb resources set: field added, reviewed settings no longer reported",
            res.returncode == 0 and after.returncode == 0 and ".mcp.json" not in after.stdout
            and 'agent_settings_reviewed = [".mcp.json"]' in read(project / "Resources" / "resources.toml"),
            tail(output(res) + output(after)))
    # Adopt from a local working copy whose upstream is unreachable: clone the copy, origin = upstream.
    work_copy, missing = work / "lib-work", (work / "remotes" / "missing.git").as_posix()
    git("clone", "--quiet", str(bare), str(work_copy), cwd=work, env=env)
    git("remote", "set-url", "origin", missing, cwd=work_copy, env=env)
    res = run([*tb, "resources", "add", str(work_copy), "--name", "lib2", "--clone"], project, env)
    lib2 = project / "Resources" / "lib2"
    origin = git("remote", "get-url", "origin", cwd=lib2, env=env) if (lib2 / ".git").exists() else ""
    R.check("tb resources add <local copy> --clone: falls back to the local copy, origin = upstream",
            res.returncode == 0 and (lib2 / "README.md").is_file() and origin == missing
            and missing in read(project / "Resources" / "resources.toml"), tail(output(res)))
    # A template clone inside a project (e.g. a resource) must refuse to init.
    nested = project / "Resources" / "template-copy"
    git("clone", "--quiet", str(origin_of(project)), str(nested), cwd=work, env=env)
    res = run([sys.executable, str(nested / "setup" / "init.py"), "--name", "x", "--yes"], nested, env, timeout=300)
    R.check("init refuses inside an agentic project", res.returncode == 1
            and "inside the agentic project" in output(res) and (nested / "setup").is_dir(), tail(output(res)))
    il.rmtree(nested)
    draft = project / "Knowledge" / "Plans" / "draft.md"
    draft.write_text("unfinished draft without frontmatter\n", encoding="utf-8")  # untracked: ignored
    paths = [p for p in (NOTE_PATH, "Resources/resources.toml", ".agents/permissions.toml")
             if (project / p).is_file()]
    res = run(["git", "add", "--", *paths], project, env)
    res = run(["git", "commit", "-m", "knowledge: add uv proxy gotcha"], project, env)  # runs pre-commit
    R.check("git commit with pre-commit hook (kb lint --staged, secrets scan); untracked draft ignored",
            res.returncode == 0, tail(output(res)))
    stage_precommit_blocks(project, env, draft)
    R.require("git: clean tree before update", git("status", "--porcelain", cwd=project, env=env) == "",
              git("status", "--porcelain", cwd=project, env=env)[:300])


def stage_permissions(project: Path, env: dict) -> None:
    """.agents/permissions.toml -> Claude settings.json permissions and Codex Starlark rules."""
    tb = tb_cmd(project)
    perms = project / ".agents" / "permissions.toml"
    R.check("init: .agents/permissions.toml seeded", perms.is_file())
    perms.write_text(read(perms) + '\n[[command]]\nprefix = ["git", "push", "--force"]\ndecision = "deny"\n'
                     'reason = "smoke"\n\n[claude]\ndeny = ["Read(./secrets/**)"]\n', encoding="utf-8")
    res = run([*tb, "agents", "link"], project, env)
    try:
        claude = json.loads(read(project / ".claude" / "settings.json")).get("permissions", {})
    except json.JSONDecodeError:
        claude = {}
    rules = read(project / ".codex" / "rules" / "project.rules")
    R.check("tb agents link: permissions.toml -> Claude permissions + Codex rules, [claude] skipped for Codex",
            res.returncode == 0 and "Bash(git push --force *)" in claude.get("deny", [])
            and "Read(./secrets/**)" in claude.get("deny", []) and "Bash(Toolbox/tb version)" in claude.get("allow", [])
            and 'pattern = ["git", "push", "--force"]' in rules and 'decision = "forbidden"' in rules
            and "[claude]" in output(res), tail(output(res)))
    res = run([*tb, "agents", "doctor"], project, env)
    R.check("tb agents doctor: permission rules up to date", res.returncode == 0, tail(output(res)))


def stage_hook_and_root(project: Path, env: dict, work: Path) -> None:
    tb = tb_cmd(project)
    prompt = json.dumps({"prompt": "как обойти прокси при загрузке uv"}, ensure_ascii=False)
    res = subprocess.run([*tb, "hook", "kb-suggest", "--agent", "claude"], cwd=project, env=env,
                         input=prompt, text=True, encoding="utf-8", capture_output=True, timeout=120)
    R.check("tb hook kb-suggest suggests the note", res.returncode == 0 and NOTE_PATH in res.stdout,
            tail(res.stdout + res.stderr))
    # A runtime that is not ready (no Python, offline) must not block the prompt (exit code 2 would).
    broken = dict(env, UV_PYTHON_INSTALL_DIR=str(work / "no-python"), UV_PYTHON_BIN_DIR=str(work / "no-python-bin"))
    res = subprocess.run([*tb, "hook", "kb-suggest", "--agent", "claude"], cwd=project, env=broken,
                         input=prompt, text=True, encoding="utf-8", capture_output=True, timeout=60)
    R.check("tb hook exits 0 and downloads nothing when the runtime is not ready",
            res.returncode == 0 and not (work / "no-python").exists(), f"rc={res.returncode} {tail(res.stderr)}")
    # Codex's hook command finds the project from a subfolder (no absolute path).
    hooks = json.loads(read(project / ".codex" / "hooks.json") or "{}")
    command = hooks["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"] if hooks else ""
    if not WINDOWS:
        res = subprocess.run(["sh", "-c", command], cwd=project / "Knowledge" / "Gotchas", env=env,
                             input=prompt, text=True, encoding="utf-8", capture_output=True, timeout=120)
        R.check("codex: hook command works from a subfolder", res.returncode == 0 and NOTE_PATH in res.stdout
                and str(project) not in command, tail(res.stdout + res.stderr))
    # An inherited TB_ROOT must not redirect the project's tb.
    res = run([*tb, "kb", "lint"], project, dict(env, TB_ROOT=str(project / "Knowledge")))
    R.check("tb ignores an inherited TB_ROOT", res.returncode == 0 and "TB_ROOT" in res.stderr
            and "1 note checked" in res.stdout and not (project / "Knowledge" / "Runtime").exists(),
            tail(output(res)))


def stage_precommit_blocks(project: Path, env: dict, draft: Path) -> None:
    """pre-commit checks what is committed: a staged broken note fixed only on disk, and secrets."""
    draft.unlink()
    bad = project / "Knowledge" / "Plans" / "broken.md"
    bad.write_text("no frontmatter\n", encoding="utf-8")
    run(["git", "add", "--", "Knowledge/Plans/broken.md"], project, env)
    bad.write_text("---\ntype: plan\n---\n", encoding="utf-8")  # unstaged change must not hide the staged one
    res = run(["git", "commit", "-m", "knowledge: broken"], project, env)
    R.check("pre-commit lints the staged content", res.returncode != 0 and "broken.md" in output(res),
            tail(output(res)))
    run(["git", "reset", "--quiet", "--", "Knowledge/Plans/broken.md"], project, env)
    bad.unlink()
    leak = project / "Toolbox" / "leak.md"
    leak.write_text("DB: postgres://app:" + "Prod1Passw0rd" + "@db.internal:5432/app\n", encoding="utf-8")
    run(["git", "add", "--", "Toolbox/leak.md"], project, env)
    res = run(["git", "commit", "-m", "toolbox: leak"], project, env)
    R.check("pre-commit blocks a password in a URL", res.returncode != 0 and "url-credentials" in output(res),
            tail(output(res)))
    run(["git", "reset", "--quiet", "--", "Toolbox/leak.md"], project, env)
    leak.unlink()


def stage_adopt(origin: Path, work: Path, env: dict, version: str) -> None:
    """Module adopt: init --with adopt, a synthetic old project under a fake HOME, the ledger pipeline up
    to a green gate and a commit through the hook, then removal of the module by update."""
    project, home = work / "adopt-project", work / "adopt-home"
    env = {**env, "HOME": str(home), "USERPROFILE": str(home)}
    git("clone", "--quiet", str(origin), str(project), cwd=work, env=env)
    args = ["--name", "adopted", "--language", "ru", "--agents", "claude,codex", "--with", "adopt", "--yes"]
    cmd = ["cmd", "/c", str(project / "init.cmd"), *args] if WINDOWS else ["sh", str(project / "init.sh"), *args]
    res = run(cmd, project, env, timeout=1200)
    R.require("adopt: init --with adopt", res.returncode == 0, tail(output(res)))
    lock = tomllib.loads(read(project / il.LOCK_PATH))
    R.check("adopt: module in the lock", "adopt" in lock["project"]["modules"], f"{lock['project']}")
    installed = [".agents/skills/adopt/SKILL.md", ".agents/skills/adopt/rules.md",
                 ".agents/skills/adopt/templates/adopt.toml", "Toolbox/agentic/adopt.py",
                 ".claude/skills/adopt/SKILL.md", ".claude/agents/adopt-worker.md", ".codex/agents/adopt-auditor.toml"]
    R.check("adopt: skill, tb code and subagents installed", all((project / p).exists() for p in installed),
            f"{[p for p in installed if not (project / p).exists()]}")
    R.check("adopt: auditor runs on the strong model", "model: opus" in read(project / ".claude/agents/adopt-auditor.md"))

    # The old project: a repository with local-only work, a vault with wikilinks, Claude memory.
    old, vault = home / "src" / "appOld", home / "Vaults" / "App"
    repo, server = old / "api", work / "remotes" / "adopt-api.git"
    repo.mkdir(parents=True)
    git("init", "--quiet", cwd=repo, env=env)
    (repo / "README.md").write_text("# api\n", encoding="utf-8")
    git("add", "README.md", cwd=repo, env=env)
    git("commit", "--quiet", "-m", "init", cwd=repo, env=env)
    git("clone", "--quiet", "--bare", str(repo), str(server), cwd=work, env=env)
    git("remote", "add", "origin", str(server), cwd=repo, env=env)
    git("fetch", "--quiet", "origin", cwd=repo, env=env)
    git("checkout", "--quiet", "-b", "wip", cwd=repo, env=env)
    (repo / "wip.txt").write_text("wip\n", encoding="utf-8")
    git("add", "wip.txt", cwd=repo, env=env)
    git("commit", "--quiet", "-m", "wip", cwd=repo, env=env)
    (vault / ".obsidian").mkdir(parents=True)
    (vault / "decisions").mkdir()
    (vault / "decisions" / "2026-01-05-api-tokens.md").write_text(
        "# Токены API\n\nСрок жизни — сутки, см. [[cache-policy]].\n", encoding="utf-8")
    (vault / "decisions" / "cache-policy.md").write_text("# Кэш\n\nНе кэшируем ответы с токеном.\n", encoding="utf-8")
    memory = home / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(old)) / "memory"
    memory.mkdir(parents=True)
    (memory / "MEMORY.md").write_text("- [api](api.md)\n", encoding="utf-8")

    tb = tb_cmd(project)
    res = run([*tb, "adopt", "start", "move", "--old-root", str(old), "--archive-dir", str(home / "Archive")],
              project, env)
    task = project / "Knowledge" / "Tasks" / "move"
    R.check("tb adopt start", res.returncode == 0 and (task / "index.md").is_file() and (task / "adopt.toml").is_file(),
            tail(output(res)))
    res = run([*tb, "adopt", "inventory"], project, env)
    R.check("tb adopt inventory: finds the local-only branch",
            res.returncode == 0 and "with local work: 1" in res.stdout and "appOld/api" in res.stdout, tail(output(res)))
    res = run([*tb, "adopt", "sources", "--vault", str(vault)], project, env)
    R.check("tb adopt sources: vault folder and Claude memory",
            res.returncode == 0 and 'folder = "Decisions"' in res.stdout and 'kind = "claude-memory"' in res.stdout,
            tail(output(res)))
    cfg = task / "adopt.toml"
    cfg.write_text(read(cfg) + '\n[[source]]\nname = "decisions"\nkind = "vault"\npaths = ["~/Vaults/App/decisions"]\n'
                               'folder = "Decisions"\n', encoding="utf-8")
    for args_ in (["manifest"], ["slugmap"]):
        res = run([*tb, "adopt", *args_], project, env)
        R.check(f"tb adopt {args_[0]}", res.returncode == 0, tail(output(res)))
    for slug, title in (("api-tokens", "Токены API"), ("cache-policy", "Кэш ответов")):
        run([*tb, "kb", "new", "decision", slug, "--title", title, "--description", f"{title}: решение"], project, env)
    note = project / "Knowledge" / "Decisions" / "api-tokens.md"
    il.write_file(project, "Knowledge/Decisions/api-tokens.md",
                  (read(note).rstrip("\n") + "\n\nСрок жизни — сутки, см. [[cache-policy]].\n").encode("utf-8"), text=True)
    res = run([*tb, "adopt", "links", "--write"], project, env)
    R.check("tb adopt links --write: wikilink -> relative link",
            res.returncode == 0 and "[Кэш ответов](cache-policy.md)" in read(note), tail(output(res)) + read(note)[-200:])
    entries = [line for line in read(task / "ledger" / "decisions" / "manifest.txt").splitlines()
               if line and not line.startswith("#")]
    batch = task / "ledger" / "decisions" / "01.md"

    def write_batch(audit: str) -> None:
        targets = {"2026-01-05-api-tokens": "Knowledge/Decisions/api-tokens.md",
                   "cache-policy": "Knowledge/Decisions/cache-policy.md"}
        rows = [f"| {e} | migrated | {targets[Path(e).stem]} | | {audit} |" for e in entries]
        batch.write_text("# decisions / 01\n\n| Источник | Вердикт | Цель | Причина | Аудит |\n|---|---|---|---|---|\n"
                         + "\n".join(rows) + "\n", encoding="utf-8")

    write_batch("")
    res = run([*tb, "adopt", "check", "decisions"], project, env)
    R.check("tb adopt check: RED without the audit", res.returncode == 1 and "RED" in res.stdout, tail(output(res)))
    res = run([*tb, "adopt", "check", "decisions", "01", "--pre-audit"], project, env)
    R.check("tb adopt check --pre-audit: GREEN", res.returncode == 0, tail(output(res)))
    write_batch("ok")
    res = run([*tb, "adopt", "gate"], project, env)
    R.check("tb adopt gate: GREEN", res.returncode == 0 and "GREEN" in res.stdout, tail(output(res)))
    res = run([*tb, "adopt", "archive", "old-vault", str(vault)], project, env)
    archive = home / "Archive" / "old-vault.tgz"
    R.check("tb adopt archive: verified, mode 600", res.returncode == 0 and archive.is_file()
            and (WINDOWS or archive.stat().st_mode & 0o777 == 0o600), tail(output(res)))
    run(["git", "add", "--", "Knowledge"], project, env)
    res = run(["git", "commit", "-m", "knowledge: adopt pilot batch"], project, env)  # runs pre-commit
    R.check("adopt: task and notes committed through the pre-commit hook", res.returncode == 0, tail(output(res)))

    res = run([*tb, "update", "fetch", "--ref", f"v{version}"], project, env)
    script = f"Runtime/update/{version}/setup/update.py"
    R.require("adopt: fetch the installed release to change modules", res.returncode == 0, tail(output(res)))
    res = run([*tb, "run", script, "apply", "--project", str(project), "--yes", "--remove-module", "adopt"],
              project, env)
    R.require("update.py apply --remove-module adopt", res.returncode == 0, tail(output(res)))
    lock = tomllib.loads(read(project / il.LOCK_PATH))
    gone = [p for p in (".agents/skills/adopt", "Toolbox/agentic/adopt.py", "Toolbox/agentic/adopt_sources.py",
                        ".agents/agents/adopt-worker.md") if (project / p).exists()]
    R.check("remove-module adopt: module files deleted, lock updated",
            not gone and "adopt" not in lock["project"]["modules"]
            and not any("adopt" in f for f in lock["files"]), f"left: {gone}")
    R.check("remove-module adopt: the task data stays",
            (task / "ledger" / "decisions" / "01.md").is_file() and (task / "adopt.toml").is_file())
    res = run([*tb, "agents", "link"], project, env)
    R.check("after removal: tb agents link drops the subagents and the skill link",
            res.returncode == 0 and not (project / ".claude/agents/adopt-worker.md").exists()
            and not (project / ".claude/skills/adopt").exists(), tail(output(res)))
    res = run([*tb, "adopt", "status"], project, env)
    R.check("after removal: no tb adopt", res.returncode != 0 and "invalid choice" in output(res), tail(output(res)))
    for args_ in (["kb", "lint"], ["agents", "doctor"]):
        res = run([*tb, *args_], project, env)
        R.check(f"after removal: tb {' '.join(args_)}", res.returncode == 0, tail(output(res)))


def stage_next_release(origin: Path, lock: dict, env: dict, version: str) -> tuple[str, dict]:
    new = bump_minor(version)
    files = lock["files"]
    skills = sorted(p for p, rec in files.items()
                    if rec.get("class") == "managed" and p.startswith(".agents/skills/") and p.endswith("/SKILL.md"))
    if len(skills) < 2:
        raise Stop("need at least two managed skills in the lock")
    if len(skills) < 4:
        raise Stop("need at least four managed skills in the lock")
    changed, local_edit, take, keep = skills[-1], skills[0], skills[1], skills[2]
    marker = f"<!-- smoke: template v{new} -->"
    for path in (changed, take, keep, "Knowledge/_templates/gotcha.md"):
        sources = payload_sources(origin, files[path]["module"], path)
        if not sources:
            raise Stop(f"no payload source for {path}")
        for src in sources:
            src.write_text(read(src).rstrip("\n") + f"\n\n{marker}\n", encoding="utf-8")
    removed = "Knowledge/Examples/README.md"
    for src in payload_sources(origin, "knowledge", removed):
        src.unlink()
    block_line = f"Smoke block line v{new}."
    for src in payload_sources(origin, "core", "AGENTS.md"):
        src.write_text(insert_after_marker(read(src), block_line), encoding="utf-8")
    new_file = ".agents/docs/smoke-new.md"
    (origin / il.MODULES_DIR / "core" / new_file).write_text("# Smoke\n", encoding="utf-8")
    (origin / il.VERSION_FILE).write_text(new + "\n", encoding="utf-8")
    changelog = origin / "CHANGELOG.md"
    changelog.write_text(f"## {new}\n\n- Smoke test release.\n\n" + read(changelog), encoding="utf-8")
    migration = origin / il.MIGRATIONS_DIR / f"{new}_smoke.py"
    migration.parent.mkdir(parents=True, exist_ok=True)
    migration.write_text(
        "from pathlib import Path\n\n\ndef migrate(root: Path) -> None:\n"
        "    (root / '.agents' / 'smoke-migration.txt').write_text('done\\n', encoding='utf-8')\n",
        encoding="utf-8")
    git("add", "-A", cwd=origin, env=env)
    git("commit", "--quiet", "--no-verify", "-m", f"release v{new}", cwd=origin, env=env)
    git("tag", f"v{new}", cwd=origin, env=env)
    R.check(f"template v{new} released (skill, AGENTS block, new file, migration)", True)
    return new, {"changed": changed, "local_edit": local_edit, "marker": marker, "block_line": block_line,
                 "new_file": new_file, "take": take, "keep": keep, "removed": removed,
                 "seeded": "Knowledge/_templates/gotcha.md",
                 "commit": git("rev-parse", "HEAD", cwd=origin, env=env)}


def stage_update(project: Path, env: dict, new: str, info: dict) -> None:
    tb = tb_cmd(project)
    local_line = "Local smoke edit."
    project_line = "Smoke project line."
    edited = (info["local_edit"], "AGENTS.md", info["take"], info["keep"], info["seeded"])
    for path, line in ((info["local_edit"], local_line), ("AGENTS.md", project_line),
                       (info["take"], local_line), (info["keep"], local_line), (info["seeded"], local_line)):
        target = project / path
        il.write_file(project, path, (read(target).rstrip("\n") + f"\n\n{line}\n").encode("utf-8"), text=True)
    git("add", "--", *edited, cwd=project, env=env)
    res = run(["git", "commit", "-m", "agents: local smoke edits"], project, env)
    R.require("git commit of local edits", res.returncode == 0, tail(output(res)))

    res = run([*tb, "update", "fetch"], project, env)
    fetched = project / "Runtime" / "update" / new
    R.require("tb update fetch", res.returncode == 0 and (fetched / "setup" / "update.py").is_file(),
              tail(output(res)))
    script = f"Runtime/update/{new}/setup/update.py"
    res = run([*tb, "run", script, "plan", "--project", str(project), "--json", "--language", "en"], project, env)
    try:
        en = {f["path"]: f["status"] for f in json.loads(res.stdout)["files"]}
    except (json.JSONDecodeError, KeyError):
        en = {}
    R.check("plan --language en: unchanged managed files are updated, AGENTS.md block too",
            en.get(".agents/docs/concept.md") == "update" and en.get("AGENTS.md") == "update", tail(output(res)))
    compose = ["--add-module", "devcontainer"]
    res = run([*tb, "run", script, "plan", "--project", str(project), "--json", *compose], project, env)
    try:
        plan = json.loads(res.stdout)
    except json.JSONDecodeError:
        plan = None
    R.require("update.py plan --json", res.returncode == 0 and plan is not None, tail(output(res)))
    status = {f["path"]: f["status"] for f in plan["files"]}
    expected = {info["changed"]: "update", "AGENTS.md": "update", info["new_file"]: "add",
                info["local_edit"]: "local-modified", info["take"]: "conflict", info["keep"]: "conflict",
                info["removed"]: "remove", info["seeded"]: "seeded-changed",
                ".devcontainer/Dockerfile": "add", ".devcontainer/devcontainer.json": "add",
                ".devcontainer/README.md": "add"}
    wrong = {p: status.get(p) for p, s in expected.items() if status.get(p) != s}
    R.check("plan: expected statuses", not wrong, f"got {wrong}")
    others = {p: s for p, s in status.items() if p not in expected and s != "unchanged"}
    R.check("plan: everything else unchanged", not others, f"{others}")
    R.check("plan: migration listed", any(m.endswith(f"{new}_smoke.py") for m in plan["migrations"]),
            f"{plan['migrations']}")
    R.check("plan: saved Runtime/update/plan.json", (project / "Runtime" / "update" / "plan.json").is_file())

    res = run([*tb, "run", script, "apply", "--project", str(project), "--yes", *compose,
               "--take-template", info["take"], "--keep-local", info["keep"]], project, env)
    R.require("update.py apply --yes", res.returncode == 0, tail(output(res)))
    R.check("apply: branch created", git("branch", "--show-current", cwd=project, env=env) == f"agentic/update-{new}")
    R.check("apply: managed skill updated", info["marker"] in read(project / info["changed"]))
    agents_md = read(project / "AGENTS.md")
    R.check("apply: AGENTS.md block updated, project part kept",
            info["block_line"] in agents_md and project_line in agents_md)
    R.check("apply: new managed file added", (project / info["new_file"]).is_file())
    R.check("apply: local modification kept", local_line in read(project / info["local_edit"]))
    R.check("apply: --take-template", info["marker"] in read(project / info["take"])
            and local_line not in read(project / info["take"]))
    R.check("apply: --keep-local", info["marker"] not in read(project / info["keep"])
            and local_line in read(project / info["keep"]))
    R.check("apply: removed file deleted", not (project / info["removed"]).exists())
    R.check("apply: seeded file untouched", local_line in read(project / info["seeded"])
            and info["marker"] not in read(project / info["seeded"]))
    R.check("apply: --add-module devcontainer", (project / ".devcontainer" / "Dockerfile").is_file())
    R.check("apply: migration ran", (project / ".agents" / "smoke-migration.txt").is_file())
    lock = tomllib.loads(read(project / il.LOCK_PATH))
    R.check(f"apply: lock version {new}", lock["template"]["version"] == new
            and lock["template"]["commit"] == info["commit"], f"{lock['template']}")
    R.check("apply: lock modules include devcontainer", "devcontainer" in lock["project"]["modules"]
            and info["removed"] not in lock["files"], f"{lock['project']}")
    for args in (["kb", "lint"], ["agents", "link"], ["agents", "doctor"]):
        res = run([*tb, *args], project, env)
        R.check(f"after update: tb {' '.join(args)}", res.returncode == 0, tail(output(res)))


def stage_dev_release(origin: Path, work: Path, env: dict, released: str) -> None:
    """A project initialized from an unreleased (X.Y.Z-dev) template gets release X.Y.Z."""
    dev = bump_minor(released) + "-dev"
    (origin / il.VERSION_FILE).write_text(dev + "\n", encoding="utf-8")
    git("commit", "--quiet", "--no-verify", "-am", f"start v{dev}", cwd=origin, env=env)
    project = work / "dev-project"
    git("clone", "--quiet", str(origin), str(project), cwd=work, env=env)
    res = run([sys.executable, str(project / "setup" / "init.py"), "--name", "dev", "--yes", "--skip-setup"],
              project, env, timeout=300)
    R.check("init from a development state warns", res.returncode == 0 and "development state" in output(res),
            tail(output(res)))
    release = release_of(dev)
    (origin / il.VERSION_FILE).write_text(release + "\n", encoding="utf-8")
    git("commit", "--quiet", "--no-verify", "-am", f"release v{release}", cwd=origin, env=env)
    git("tag", f"v{release}", cwd=origin, env=env)
    res = run([*tb_cmd(project), "update", "fetch"], project, env)
    R.check(f"v{dev} project: tb update fetch offers v{release}",
            res.returncode == 0 and (project / "Runtime" / "update" / release / "setup" / "update.py").is_file(),
            tail(output(res)))


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="End-to-end smoke test of the template.")
    parser.add_argument("--keep", action="store_true", help="keep the temporary folder")
    args = parser.parse_args()
    work = Path(tempfile.mkdtemp(prefix="agentic-smoke-")).resolve()
    origin, project = work / "agentic-project-template", work / NAME
    env = make_env(work)
    print(f"Smoke test of {TEMPLATE_ROOT} in {work}", flush=True)
    try:
        version, commit = stage_release(origin, env)
        stage_refusals(origin, work, env)
        lock = stage_init(origin, project, env, version, commit)
        stage_toolbox(project, env, work)
        stage_adopt(origin, work, env, version)
        new, info = stage_next_release(origin, lock, env, version)
        stage_update(project, env, new, info)
        stage_dev_release(origin, work, env, new)
    except Stop as exc:
        if exc.recorded:
            print(f"Stopped after \"{exc}\"; the remaining steps were skipped.")
        else:
            R.check("stopped", False, str(exc))
    except Exception as exc:  # noqa: BLE001 — report, do not hide the traceback
        R.check("unexpected error", False, f"{type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
    passed = len(R.items) - R.failed
    print(f"\nSmoke test: {passed} passed, {R.failed} failed.")
    if R.failed or args.keep:
        print(f"Work folder kept: {work}")
    else:
        il.rmtree(work)
    return 1 if R.failed else 0


if __name__ == "__main__":
    sys.exit(main())
