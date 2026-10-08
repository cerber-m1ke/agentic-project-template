# /// script
# requires-python = ">=3.12"
# dependencies = ["tomli-w>=1"]
# [tool.uv]
# exclude-newer = "2026-10-01T00:00:00Z"
# ///
"""Turn a fresh clone of agentic-project-template into an Agentic Project.

Run through ./init.sh (init.cmd on Windows), or directly:
    payload/modules/core/Toolbox/tb run setup/init.py --name demo --yes
Without --yes it only prints the plan. See setup/INIT.md and setup/DESIGN.md §6.1.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # keep the template tree pristine (no setup/__pycache__)

import argparse
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import installer_lib as il  # noqa: E402

TEMPLATE_ROOT = Path(__file__).resolve().parents[1]

# Template files removed by init (DESIGN §6.1 step 5); README.md, AGENTS.md, .gitignore and
# .gitattributes are then replaced by the payload versions.
INSTALLER_PATHS = ("setup", "payload", "init.sh", "init.cmd", "README.md", "README.en.md",
                   "AGENTS.md", "CHANGELOG.md", ".gitignore", ".gitattributes")
# Never part of the pristine check: tb's runtime and Python caches.
STATUS_EXCLUDES = (":(exclude)Runtime", ":(exclude,glob)**/__pycache__/**")
# Top-level names allowed besides INSTALLER_PATHS when the template is not a git clone (an unpacked
# archive): tb's runtime and OS/IDE junk. Anything else is a foreign file and needs --force.
NON_GIT_ALLOWED = ("Runtime", ".DS_Store", "Thumbs.db", "desktop.ini", ".idea", "__MACOSX")


@dataclass
class Plan:
    root: Path
    version: str
    source: str
    commit: str
    has_git: bool
    name: str
    language: str
    profile: str
    modules: list[str]
    module_objs: dict[str, il.Module]
    agents: list[str]
    entries: dict[str, il.Entry]
    created: str
    kept: list[str]
    foreign: list[str]
    warnings: list[str]


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="init",
        description="Initialize an Agentic Project from this template. "
                    "Without --yes only the plan is printed.")
    p.add_argument("--name", help="project name (default: folder name)")
    p.add_argument("--language", default="ru", help="project language: ru or en (default: ru)")
    p.add_argument("--profile", default="software", help="profile: software or generic (default: software)")
    p.add_argument("--with", dest="with_", action="append", default=[], metavar="MODULE",
                   help="include an optional module (repeatable)")
    p.add_argument("--without", action="append", default=[], metavar="MODULE",
                   help="exclude a non-required module (repeatable)")
    p.add_argument("--agents", help="comma-separated agents to link on this machine, e.g. claude,codex")
    p.add_argument("--yes", action="store_true", help="perform the initialization (destructive)")
    p.add_argument("--dry-run", action="store_true", help="print the plan with the full file list and exit")
    p.add_argument("--force", action="store_true",
                   help="allow init in a folder that is not a git clone and contains files other than the template")
    p.add_argument("--skip-setup", action="store_true",
                   help="do not run Toolbox/tb setup and module post-install steps; print them instead")
    return p.parse_args(argv)


def split_csv(value: str | None) -> list[str]:
    if value is None:
        return []
    items: list[str] = []
    for part in value.split(","):
        part = part.strip()
        if part and part not in items:
            items.append(part)
    return items


def foreign_files(root: Path) -> list[str]:
    """Top-level entries of a non-git template folder that are not part of the template."""
    allowed = set(INSTALLER_PATHS) | set(NON_GIT_ALLOWED)
    return sorted(p.name + ("/" if p.is_dir() and not p.is_symlink() else "")
                  for p in root.iterdir() if p.name not in allowed)


def check_template(root: Path, force: bool = False) -> tuple[list[str], list[str]]:
    """Raise unless `root` is a pristine template clone; return (warnings, foreign files)."""
    missing = [p for p in (il.VERSION_FILE, il.MODULES_DIR, il.PROFILES_DIR) if not (root / p).exists()]
    if missing:
        raise il.InstallerError(
            f"{root} is not an agentic-project-template folder (missing: {', '.join(missing)})")
    if (root / il.LOCK_PATH).exists():
        raise il.InstallerError(f"{il.LOCK_PATH} already exists: this folder is already an agentic project")
    for parent in root.resolve().parents:
        if (parent / il.LOCK_PATH).is_file():
            # e.g. Resources/agentic-project-template of a project: a resource, not a new project.
            raise il.InstallerError(
                f"this template clone lives inside the agentic project {parent} "
                f"({root.resolve().relative_to(parent).as_posix()}): init would replace its .git. "
                "To create a project, clone the template into a folder of its own")
    if shutil.which("git") is None:
        raise il.InstallerError("git is not installed (or not on PATH); install git and re-run")
    dot_git = root / ".git"
    if dot_git.is_symlink() or (dot_git.exists() and not dot_git.is_dir()):
        raise il.InstallerError(
            f"{dot_git} is not a directory (git worktree or submodule?). Init replaces .git with a new "
            "repository: clone the template into a normal folder, not a worktree/submodule")
    if not dot_git.exists():
        foreign = foreign_files(root)
        if foreign and not force:
            raise il.InstallerError(
                "this folder is not a git clone and contains files that are not part of the template:\n  "
                + "\n  ".join(foreign)
                + "\nInit would turn them into project files (same paths are overwritten) and commit them. "
                  "Unpack the template into an empty folder, or re-run with --force")
        warnings = ["not a git clone: cannot verify that the template is unmodified; template commit is unknown"]
        if foreign:
            warnings.append("--force: files that are not part of the template stay in the project and are "
                            f"committed (same paths are overwritten): {', '.join(foreign)}")
        return warnings, [f.rstrip("/") for f in foreign]
    top = il.git("rev-parse", "--show-toplevel", cwd=root)
    if top.returncode != 0 or Path(top.stdout.strip()).resolve() != root.resolve():
        raise il.InstallerError(f"{root}/.git is not a usable git repository")
    status = il.git("status", "--porcelain", "--untracked-files=all", "--", ".", *STATUS_EXCLUDES, cwd=root)
    if status.returncode != 0:
        raise il.InstallerError(f"git status failed: {status.stderr.strip()}")
    dirty = [line for line in status.stdout.splitlines() if line.strip()]
    if dirty:
        shown = "\n  ".join(dirty[:20]) + ("\n  …" if len(dirty) > 20 else "")
        raise il.InstallerError(
            "the template has local changes; init needs a pristine clone "
            f"(commit, stash or discard them first):\n  {shown}")
    return [], []


def release_warnings(root: Path, version: str, commit: str) -> list[str]:
    """Warn when the project would not start from a published release."""
    if not il.is_release(version):
        return [f"template v{version} is a development state, not a release: updates will offer "
                f"v{version.removesuffix('-dev')} once it is tagged"]
    if commit:
        tags = il.git("tag", "--points-at", "HEAD", cwd=root)
        if tags.returncode == 0 and f"v{version}" not in tags.stdout.split():
            return [f"HEAD is not the release tag v{version}: the project records v{version}, "
                    "but its files may differ from that release"]
    return []


def kept_template_files(root: Path, entries: dict[str, il.Entry]) -> list[str]:
    """Tracked template files that init neither deletes nor replaces."""
    res = il.git("ls-files", "-z", cwd=root)
    if res.returncode != 0:
        return []
    kept = []
    for path in res.stdout.split("\0"):
        if not path or path in entries:
            continue
        if any(path == p or path.startswith(p + "/") for p in INSTALLER_PATHS):
            continue
        kept.append(path)
    return kept


def build_plan(args: argparse.Namespace) -> Plan:
    root = TEMPLATE_ROOT
    warnings, foreign = check_template(root, args.force)
    version = il.read_version(root)
    has_git = il.has_own_git(root)
    source, commit = il.template_git_info(root)
    warnings += release_warnings(root, version, commit)

    name = (args.name if args.name is not None else root.name).strip()
    if not name:
        raise il.InstallerError("project name is empty")
    if any(ord(ch) < 32 or ord(ch) == 127 or ch in '"\\' for ch in name) or len(name) > 100:
        raise il.InstallerError(
            f"invalid project name {name!r}: use at most 100 characters without quotes (\"), "
            "backslashes or control characters (pass --name)")
    if args.language not in il.LANGS:
        raise il.InstallerError(f"unknown language '{args.language}' (available: {', '.join(il.LANGS)})")

    profile = il.load_profile(root, args.profile)
    module_objs = il.load_modules(root)
    modules = il.resolve_modules(profile, module_objs, split_csv(",".join(args.with_)),
                                 split_csv(",".join(args.without)))
    created = date.today().isoformat()
    ctx = il.Context(project_name=name, language=args.language, profile=args.profile, date=created,
                     template_root=root)
    entries = il.materialize(root, modules, module_objs, ctx)
    if il.LOCK_PATH in entries:
        raise il.InstallerError(f"payload must not contain {il.LOCK_PATH}")

    agents = split_csv(args.agents)
    if args.agents is not None and not agents:
        raise il.InstallerError("--agents is empty")
    known_agents = il.available_agents(entries)
    unknown = [a for a in agents if a not in known_agents]
    if unknown:
        raise il.InstallerError(
            f"unknown agent(s): {', '.join(unknown)} (available: {', '.join(known_agents) or 'none'})")

    kept = kept_template_files(root, entries) if has_git else []
    return Plan(root, version, source, commit, has_git, name, args.language, args.profile, modules,
                module_objs, agents, entries, created, kept, foreign, warnings)


def setup_commands(plan: Plan) -> list[list[str]]:
    cmds = [["setup"] + (["--agents", ",".join(plan.agents)] if plan.agents else [])]
    for name in plan.modules:
        cmds.extend(plan.module_objs[name].post_install)
    return cmds


def tb_display() -> str:
    return "Toolbox\\tb.cmd" if os.name == "nt" else "Toolbox/tb"


def print_plan(plan: Plan, full: bool) -> None:
    counts = {cls: sum(1 for e in plan.entries.values() if e.cls == cls) for cls in il.CLASSES}
    commit = plan.commit[:12] if plan.commit else "unknown"
    print(f"Agentic project init — template v{plan.version} (commit {commit})")
    print(f"  folder:    {plan.root}")
    print(f"  source:    {plan.source or '(none)'}")
    print(f"  name:      {plan.name}")
    print(f"  language:  {plan.language}")
    print(f"  profile:   {plan.profile}")
    print(f"  modules:   {', '.join(plan.modules)}")
    print(f"  agents:    {', '.join(plan.agents) if plan.agents else '(not set; tb setup decides)'}")
    print(f"  files:     {len(plan.entries)} "
          f"(managed {counts['managed']}, seeded {counts['seeded']}, block {counts['block']})")
    for w in plan.warnings:
        print(f"warning: {w}", file=sys.stderr)
    if plan.kept:
        print(f"warning: template files not handled by init stay in the project: {', '.join(plan.kept)}",
              file=sys.stderr)
    print("Steps:")
    present = [p for p in INSTALLER_PATHS if (plan.root / p).exists() or (plan.root / p).is_symlink()]
    print(f"  1. Delete the installer: {', '.join(p + '/' if (plan.root / p).is_dir() else p for p in present)}")
    print(f"  2. Write {len(plan.entries)} project files and {il.LOCK_PATH}")
    print(f"  3. Replace .git with a new repository (branch master); "
          f"commit \"agentic: init from template v{plan.version}\"")
    step = 4
    for cmd in setup_commands(plan):
        print(f"  {step}. Run {tb_display()} {' '.join(cmd)}")
        step += 1
    if full:
        print("Files:")
        for name in plan.modules:
            for entry in sorted((e for e in plan.entries.values() if e.module == name), key=lambda e: e.path):
                flag = " (+x)" if entry.executable else ""
                print(f"  {entry.module:<12} {entry.cls:<8} {entry.path}{flag}")


def git_checked(*args: str, cwd: Path) -> str:
    res = il.git(*args, cwd=cwd)
    if res.returncode != 0:
        raise il.InstallerError(f"git {' '.join(args)} failed: {(res.stderr or res.stdout).strip()}")
    return res.stdout


def local_git_settings(root: Path) -> list[tuple[str, str]]:
    """user.* settings of the template clone's own .git/config (identity, signing key): init replaces
    .git, and the first commit must be made by the same author that git_identity_problem() checked."""
    res = il.git("config", "--local", "--get-regexp", r"^user\.", cwd=root)
    if res.returncode != 0:
        return []
    pairs = []
    for line in res.stdout.splitlines():
        key, _, value = line.partition(" ")
        if key:
            pairs.append((key, value))
    return pairs


def commit_paths(plan: Plan) -> list[str]:
    """Exactly what the initial commit contains: payload files, the lock, template files that init
    keeps and (with --force) foreign files. Untracked leftovers of the template folder (a local
    CLAUDE.md alias, .obsidian/, editor folders) are never committed."""
    paths = [*plan.entries, il.LOCK_PATH, *plan.kept, *plan.foreign]
    return sorted(dict.fromkeys(paths))


def perform(plan: Plan) -> None:
    root = plan.root
    os.chdir(root)
    settings = local_git_settings(root) if plan.has_git else []
    restore = ("Restore the template with `git checkout -- . && git clean -fd` in this folder "
               "(its .git is still in place) and re-run init." if plan.has_git else
               "Unpack the template into an empty folder again and re-run init.")

    # 1–2. Delete the installer (imports are done; the running script survives its own deletion),
    # then write the project files and the lock.
    try:
        for rel_path in INSTALLER_PATHS:
            path = root / rel_path
            if path.exists() or path.is_symlink():
                il.remove_path(path)
        for entry in plan.entries.values():
            il.write_entry(root, entry)
        files = {path: entry.lock_record() for path, entry in plan.entries.items()}
        project = {"name": plan.name, "language": plan.language, "profile": plan.profile,
                   "modules": plan.modules, "created": plan.created}
        il.write_lock(root, il.make_lock(plan.source, plan.version, plan.commit, project, files))
    except OSError as exc:
        raise il.InstallerError(f"cannot write the project files: {exc}\n{restore}") from exc

    # 3. Fresh repository with one commit of explicit paths (-f: a global excludes file of the
    # user must not silently drop project files).
    message = f"agentic: init from template v{plan.version}"
    finish = (f"The project files are written. Fix the problem, then run in this folder:\n"
              f"  git init -b master && git add -f -- . && git commit --no-verify -m \"{message}\"\n"
              f"  {tb_display()} setup")
    try:
        if plan.has_git:
            il.rmtree(root / ".git")
        git_checked("init", "--quiet", cwd=root)
        git_checked("symbolic-ref", "HEAD", "refs/heads/master", cwd=root)
        for key, value in settings:
            git_checked("config", "--local", key, value, cwd=root)
        git_checked("config", "core.hooksPath", ".agents/git-hooks", cwd=root)
        git_checked("config", "core.quotePath", "false", cwd=root)
        if os.name == "nt":
            git_checked("config", "core.longpaths", "true", cwd=root)
        paths = commit_paths(plan)
        git_checked("add", "-f", "--", *paths, cwd=root)
        executables = sorted(e.path for e in plan.entries.values() if e.executable)
        if executables:
            git_checked("update-index", "--chmod=+x", "--", *executables, cwd=root)
        staged = set(git_checked("diff", "--cached", "--name-only", "-z", cwd=root).split("\0"))
        lost = [p for p in [*plan.entries, il.LOCK_PATH] if p not in staged]
        if lost:
            raise il.InstallerError(f"files not staged for the initial commit: {', '.join(lost[:10])}")
    except (il.InstallerError, OSError) as exc:
        raise il.InstallerError(f"{exc}\n{finish}") from exc
    res = il.git("commit", "--quiet", "--no-verify", "-m", message, cwd=root)
    if res.returncode != 0:
        raise il.InstallerError(
            f"git commit failed: {(res.stderr or res.stdout).strip()}\n"
            f"The project files are written and staged. Fix the problem, then run:\n"
            f"  git commit --no-verify -m \"{message}\"\n  {tb_display()} setup")
    leftovers = il.git("status", "--porcelain", "--untracked-files=normal", cwd=root)
    if leftovers.returncode == 0 and leftovers.stdout.strip():
        print("warning: files left from the template folder are not committed (delete them or commit "
              "them yourself):\n  " + "\n  ".join(leftovers.stdout.splitlines()[:20]), file=sys.stderr)


def run_setup(plan: Plan, skip: bool) -> int:
    cmds = setup_commands(plan)
    if skip:
        print("Machine setup skipped (--skip-setup). Run later from the project root:")
        for cmd in cmds:
            print(f"  {tb_display()} {' '.join(cmd)}")
        return 0
    env = {k: v for k, v in os.environ.items() if k not in ("TB_ROOT", "AGENTIC_ROOT")}
    failed = []
    for cmd in cmds:
        print(f"$ {tb_display()} {' '.join(cmd)}", flush=True)
        if os.name == "nt":
            # One string for cmd.exe /s: survives spaces, parentheses and & in the project path.
            tbcmd = str(plan.root / "Toolbox" / "tb.cmd")
            line = 'cmd /d /s /c ""%s" %s"' % (tbcmd, subprocess.list2cmdline(cmd))
            rc = subprocess.run(line, cwd=plan.root, env=env).returncode
        else:
            rc = subprocess.run(["sh", str(plan.root / "Toolbox" / "tb"), *cmd], cwd=plan.root, env=env).returncode
        if rc != 0:
            failed.append((cmd, rc))
    for cmd, rc in failed:
        print(f"error: {tb_display()} {' '.join(cmd)} failed (exit {rc}); fix the cause and re-run it",
              file=sys.stderr)
    return 1 if failed else 0


def print_next_steps(plan: Plan) -> None:
    tb = tb_display()
    print(f"\nInitialized agentic project \"{plan.name}\" from template v{plan.version} "
          f"({plan.profile}, {plan.language}, modules: {', '.join(plan.modules)}).")
    print("Next steps:")
    print("  - Open the project with your agent; it starts from AGENTS.md. An agent that ran init by "
          "setup/INIT.md continues with its step 5 (it read the instruction before init deleted it).")
    print("  - Describe the project in AGENTS.md outside the agentic:begin/end block.")
    if "resources" in plan.modules:
        print(f"  - Register resources: {tb} resources add <url> --description \"…\" --clone")
    print("  - Commit with explicit paths, e.g.: git add AGENTS.md && git commit -m \"agentic: describe project\"")
    print(f"  - Optionally add a remote: git remote add origin <url>. Other machines: clone, then {tb} setup --agents <a,b>")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    args = parse_args(argv)
    try:
        plan = build_plan(args)
    except il.InstallerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print_plan(plan, full=args.dry_run)
    if args.dry_run:
        print("Dry run: nothing was changed.")
        return 0
    if not args.yes:
        print("Nothing was changed. Initialization is destructive (it replaces .git and deletes the "
              "installer); re-run with --yes to perform it.")
        return 2
    problem = il.git_identity_problem(plan.root)
    if problem:
        print(f"error: {problem}", file=sys.stderr)
        return 1
    try:
        perform(plan)
    except il.InstallerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: initialization interrupted: {exc}", file=sys.stderr)
        return 1
    print(f"Created the initial commit \"agentic: init from template v{plan.version}\".")
    rc = run_setup(plan, args.skip_setup)
    print_next_steps(plan)
    return rc


if __name__ == "__main__":
    sys.exit(main())
